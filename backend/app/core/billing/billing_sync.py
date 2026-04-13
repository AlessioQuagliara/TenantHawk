# =============================================================================
# backend/app/core/billing_sync.py
# =============================================================================

from __future__ import annotations

from datetime import datetime, timezone

from typing import Any

import stripe  # ty:ignore[unresolved-import]

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.infrastructure.config import settings

from app.models import (
    Sottoscrizione,
    Sottoscrizioni,
    SottoscrizioniStati,
    Tenant,
)

from app.core.billing.billing_models import (
    _calcola_scadenza_tregua,
    _e_scadenza_tregua,
    _normalizza_data_utc,
    _to_int,
    datetime_da_unix,
    piano_da_price_id,
    price_id_per_piano,
    stripe_live_sync_configurato,
)

stripe.api_key = settings.stripe_secret_key


def _obj_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    for method_name in ("to_dict_recursive", "to_dict", "serialize", "_to_dict_recursive"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                converted = method()
            except Exception:
                continue
            if isinstance(converted, dict):
                return converted

    raw_data = getattr(value, "_data", None)
    if isinstance(raw_data, dict):
        return raw_data

    try:
        converted = dict(value)
    except Exception:
        return {}
    return converted if isinstance(converted, dict) else {}


def _obj_to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None or isinstance(value, (str, bytes, dict)):
        return []
    try:
        return list(value)
    except Exception:
        return []


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str if value_str else None


def stato_interno_da_stato_stripe(stato_stripe: str | None) -> SottoscrizioniStati:
    if stato_stripe == "trialing":
        return SottoscrizioniStati.PROVA
    if stato_stripe == "active":
        return SottoscrizioniStati.ATTIVO
    if stato_stripe in {"past_due", "unpaid", "incomplete", "incomplete_expired", "paused"}:
        return SottoscrizioniStati.SOSPESO
    if stato_stripe == "canceled":
        return SottoscrizioniStati.CANCELLATO
    return SottoscrizioniStati.SCADUTO


def stato_stripe_effettivo(
    stato_stripe: str | None,
    *,
    payment_status: str | None = None,
    invoice_paid: bool = False,
) -> str | None:
    stato_normalizzato = str(stato_stripe).strip().lower() if stato_stripe else None
    payment_status_normalizzato = (
        str(payment_status).strip().lower() if payment_status else None
    )

    if invoice_paid or payment_status_normalizzato == "paid":
        if stato_normalizzato in {None, "incomplete", "past_due", "unpaid", "trialing"}:
            return "active"

    return stato_normalizzato


def invoice_pagata_da_subscription_obj(
    subscription_obj: Any,
) -> bool:
    subscription_data = _obj_to_dict(subscription_obj)
    latest_invoice = _obj_to_dict(subscription_data.get("latest_invoice"))
    if not latest_invoice:
        return False

    if latest_invoice.get("paid") is True:
        return True

    if str(latest_invoice.get("status") or "").strip().lower() == "paid":
        return True

    payment_intent = _obj_to_dict(latest_invoice.get("payment_intent"))
    if payment_intent:
        return str(payment_intent.get("status") or "").strip().lower() == "succeeded"

    return False


def estrai_current_period_end_unix_da_subscription(
    subscription_obj: Any,
) -> int | None:
    subscription_data = _obj_to_dict(subscription_obj)

    # Campo principale classico Stripe Subscription
    value = _to_int(subscription_data.get("current_period_end"))
    if value is not None:
        return value

    # Fallback su eventuali varianti "current_period.end"
    current_period = _obj_to_dict(subscription_data.get("current_period"))
    value = _to_int(current_period.get("end"))
    if value is not None:
        return value

    # Fallback su latest_invoice, utile in alcuni payload/eventi
    latest_invoice = _obj_to_dict(subscription_data.get("latest_invoice"))
    if latest_invoice:
        value = _to_int(latest_invoice.get("period_end"))
        if value is not None:
            return value

        lines_container = _obj_to_dict(latest_invoice.get("lines"))
        lines = _obj_to_list(lines_container.get("data"))
        for line in lines:
            line_data = _obj_to_dict(line)
            period = _obj_to_dict(line_data.get("period"))
            value = _to_int(period.get("end"))
            if value is not None:
                return value

    return None


def _estrai_price_id_da_subscription(subscription_obj: Any) -> str | None:
    subscription_data = _obj_to_dict(subscription_obj)
    items_container = _obj_to_dict(subscription_data.get("items"))
    items = _obj_to_list(items_container.get("data"))
    if not items:
        return None
    item_data = _obj_to_dict(items[0])
    price_obj = _obj_to_dict(item_data.get("price"))
    price_id = price_obj.get("id")
    return str(price_id) if price_id else None


def _errore_stripe_subscription_inesistente(exc: Exception) -> bool:
    if not isinstance(exc, stripe.error.InvalidRequestError):
        return False
    code = str(getattr(exc, "code", "")).lower()
    message = str(exc).lower()
    return "no such subscription" in message or (
        code == "resource_missing" and "subscription" in message
    )


def _scegli_subscription_rilevante(subscriptions_obj: Any) -> dict[str, Any] | None:
    subscriptions_data = _obj_to_dict(subscriptions_obj)
    data_raw = _obj_to_list(subscriptions_data.get("data"))
    data: list[dict[str, Any]] = []
    for item in data_raw:
        item_data = _obj_to_dict(item)
        if item_data:
            data.append(item_data)
    if not data:
        return None

    priorita_stato = {
        "active": 0,
        "trialing": 1,
        "past_due": 2,
        "unpaid": 3,
        "incomplete": 4,
        "canceled": 5,
        "incomplete_expired": 6,
    }
    data_ordinati = sorted(
        data,
        key=lambda sub: (
            priorita_stato.get(str(sub.get("status") or ""), 99),
            -int(sub.get("created") or 0),
        ),
    )
    return data_ordinati[0]


async def sincronizza_sottoscrizione_tenant_live(
    db: AsyncSession,
    *,
    tenant_obj: Tenant,
) -> tuple[Sottoscrizione | None, bool, bool, dict[str, Any] | None]:
    tenant_id = tenant_obj.id
    risultato_sottoscrizione = await db.execute(
        select(Sottoscrizione)
        .where(Sottoscrizione.tenant_id == tenant_id)
        .limit(1)
    )
    sottoscrizione = risultato_sottoscrizione.scalar_one_or_none()
    if not stripe_live_sync_configurato() or sottoscrizione is None:
        return sottoscrizione, False, False, None

    sub_obj: dict[str, Any] | None = None
    cancel_at_period_end = False
    verifica_live_ok = False
    live_details: dict[str, Any] | None = None

    if sottoscrizione.id_stripe_sottoscrizione:
        try:
            sub_obj = stripe.Subscription.retrieve(
                str(sottoscrizione.id_stripe_sottoscrizione),
                expand=[
                    "items.data.price",
                    "latest_invoice",
                    "latest_invoice.lines.data",
                    "latest_invoice.payment_intent",
                ],
            )
            sub_obj = _obj_to_dict(sub_obj)
            verifica_live_ok = True
        except stripe.error.InvalidRequestError as exc:
            if not _errore_stripe_subscription_inesistente(exc):
                return None, False, False, None
            try:
                sottoscrizione.id_stripe_sottoscrizione = None
                await db.commit()
            except Exception:
                await db.rollback()

    if sub_obj is None and sottoscrizione.id_stripe_cliente:
        try:
            elenco = stripe.Subscription.list(
                customer=str(sottoscrizione.id_stripe_cliente),
                status="all",
                limit=10,
            )
            sub_obj = _scegli_subscription_rilevante(elenco)
            verifica_live_ok = True
        except Exception:
            return None, False, False, None

    if sub_obj is None:
        if verifica_live_ok and sottoscrizione is not None:
            # Se Stripe non restituisce piu' alcuna subscription per un tenant
            # che risultava attivo/collegato, allineiamo lo stato locale.
            ha_subscription_id = bool(sottoscrizione.id_stripe_sottoscrizione)
            era_attivo = sottoscrizione.stato_piano == SottoscrizioniStati.ATTIVO
            if ha_subscription_id or era_attivo:
                try:
                    piano_corrente = sottoscrizione.piano
                    sottoscrizione_aggiornata = await sincronizza_sottoscrizione_da_stripe(
                        db,
                        tenant_id=tenant_id,
                        stripe_customer_id=(
                            str(sottoscrizione.id_stripe_cliente)
                            if sottoscrizione.id_stripe_cliente
                            else None
                        ),
                        stripe_status="canceled",
                        stripe_price_id=price_id_per_piano(piano_corrente),
                        current_period_end_unix=None,
                    )
                    if sottoscrizione_aggiornata is not None:
                        sottoscrizione_aggiornata.id_stripe_sottoscrizione = None
                        sottoscrizione = sottoscrizione_aggiornata
                    await db.commit()
                except Exception:
                    await db.rollback()
                    return None, False, False, None
        return sottoscrizione, False, verifica_live_ok, None

    try:
        current_period_end_unix = estrai_current_period_end_unix_da_subscription(sub_obj)
        latest_invoice = _obj_to_dict(sub_obj.get("latest_invoice"))
        ultimo_pagamento_ok = (
            invoice_pagata_da_subscription_obj(sub_obj) if latest_invoice else None
        )
        stripe_status_effettivo = stato_stripe_effettivo(
            str(sub_obj.get("status") or ""),
            invoice_paid=bool(ultimo_pagamento_ok),
        )
        sottoscrizione_aggiornata = await sincronizza_sottoscrizione_da_stripe(
            db,
            tenant_id=tenant_id,
            stripe_subscription_id=_str_or_none(sub_obj.get("id")),
            stripe_customer_id=_str_or_none(sub_obj.get("customer")),
            stripe_status=stripe_status_effettivo,
            stripe_price_id=_estrai_price_id_da_subscription(sub_obj),
            current_period_end_unix=current_period_end_unix,
            ultimo_pagamento_ok=ultimo_pagamento_ok,
        )
        await db.commit()
        if sottoscrizione_aggiornata is not None:
            sottoscrizione = sottoscrizione_aggiornata
        cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end"))
        live_details = {
            "current_period_end_unix": current_period_end_unix,
            "ultimo_pagamento_ok": ultimo_pagamento_ok,
            "stripe_status_effettivo": stripe_status_effettivo,
            "stripe_status_raw": _str_or_none(sub_obj.get("status")),
            "stripe_customer_id": _str_or_none(sub_obj.get("customer")),
            "stripe_subscription_id": _str_or_none(sub_obj.get("id")),
            "cancel_at_period_end": cancel_at_period_end,
        }
    except Exception:
        await db.rollback()
        return None, False, False, None

    return sottoscrizione, cancel_at_period_end, verifica_live_ok, live_details


async def trova_sottoscrizione_per_riferimenti(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    stripe_subscription_id: str | None = None,
    stripe_customer_id: str | None = None,
) -> Sottoscrizione | None:
    if stripe_subscription_id:
        result = await db.execute(
            select(Sottoscrizione)
            .where(Sottoscrizione.id_stripe_sottoscrizione == stripe_subscription_id)
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row

    if stripe_customer_id:
        result = await db.execute(
            select(Sottoscrizione)
            .where(Sottoscrizione.id_stripe_cliente == stripe_customer_id)
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row

    if tenant_id is not None:
        result = await db.execute(
            select(Sottoscrizione)
            .where(Sottoscrizione.tenant_id == tenant_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    return None


async def sincronizza_sottoscrizione_da_stripe(
    db: AsyncSession,
    *,
    tenant_id: int | None = None,
    stripe_subscription_id: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_status: str | None = None,
    stripe_price_id: str | None = None,
    current_period_end_unix: int | None = None,
    ultimo_pagamento_ok: bool | None = None,
) -> Sottoscrizione | None:
    row = await trova_sottoscrizione_per_riferimenti(
        db,
        tenant_id=tenant_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
    )

    piano_da_stripe = piano_da_price_id(stripe_price_id)
    if row is None:
        piano = piano_da_stripe or Sottoscrizioni.BASE
    else:
        piano = piano_da_stripe or row.piano
    stato = stato_interno_da_stato_stripe(stripe_status)
    fine_periodo = datetime_da_unix(current_period_end_unix)
    fallback_grace_deadline: datetime | None = None

    if row is None:
        if tenant_id is None:
            return None
        row = Sottoscrizione(
            tenant_id=tenant_id,
            piano=piano,
            stato_piano=stato,
            fine_periodo_corrente=fine_periodo,
            ultimo_pagamento_ok=ultimo_pagamento_ok,
            id_stripe_cliente=stripe_customer_id,
            id_stripe_sottoscrizione=stripe_subscription_id,
        )
        db.add(row)
        await db.flush()

    row.piano = piano
    adesso_utc = datetime.now(timezone.utc)
    if fine_periodo is not None:
        fine_periodo_utc = (
            fine_periodo if fine_periodo.tzinfo else fine_periodo.replace(tzinfo=timezone.utc)
        )
        if fine_periodo_utc <= adesso_utc:
            # Trial realmente concluso: scade lato interno.
            if stato == SottoscrizioniStati.PROVA:
                stato = SottoscrizioniStati.SCADUTO

    if stato == SottoscrizioniStati.SOSPESO:
        fine_corrente_utc = _normalizza_data_utc(row.fine_periodo_corrente)
        if row.stato_piano != SottoscrizioniStati.SOSPESO:
            fallback_grace_deadline = _calcola_scadenza_tregua(adesso_utc)
        elif fine_corrente_utc is None:
            fallback_grace_deadline = _calcola_scadenza_tregua(adesso_utc)
        elif _e_scadenza_tregua(fine_corrente_utc):
            # Se siamo gia' in tregua, non estenderla a ogni webhook.
            fallback_grace_deadline = fine_corrente_utc
        elif fine_corrente_utc > adesso_utc:
            # Stato sospeso con periodo futuro: aspettiamo la data e poi avviamo tregua.
            fallback_grace_deadline = fine_corrente_utc
        else:
            # Stato sospeso con data scaduta non marcata: avvio tregua vera.
            fallback_grace_deadline = _calcola_scadenza_tregua(adesso_utc)

    row.stato_piano = stato
    if fallback_grace_deadline is not None:
        row.fine_periodo_corrente = fallback_grace_deadline
    elif fine_periodo is not None:
        row.fine_periodo_corrente = fine_periodo
    elif stato in {SottoscrizioniStati.SCADUTO, SottoscrizioniStati.CANCELLATO}:
        # Per stati terminali azzeriamo la data.
        row.fine_periodo_corrente = None
    if ultimo_pagamento_ok is not None:
        row.ultimo_pagamento_ok = bool(ultimo_pagamento_ok)
    if stripe_customer_id:
        row.id_stripe_cliente = stripe_customer_id
    if stripe_subscription_id:
        row.id_stripe_sottoscrizione = stripe_subscription_id
    await db.flush()
    return row
