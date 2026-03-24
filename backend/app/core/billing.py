# =============================================================================
# backend/app/core/billing.py
# =============================================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from typing import Any

import stripe  # ty:ignore[unresolved-import]

from sqlalchemy import delete, select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from app.models import (
    Sottoscrizione,
    Sottoscrizioni,
    SottoscrizioniStati,
    Tenant,
    TokenResetPassword,
    Utente,
    UtenteRuoloTenant,
)

# -----------------------------------------------------------------------------
# LIMITI PER PIANO ------------------------------------------------------------
# -----------------------------------------------------------------------------

GIORNI_PROVA_DEFAULT = 14
GIORNI_TREGUA_DISATTIVAZIONE = 14
TREGUA_MARKER_MICROSECOND = 987654

LIMITI_UTENTI_PER_PIANO = {
    Sottoscrizioni.BASE: 3,
    Sottoscrizioni.PRO: 10,
    Sottoscrizioni.COMPANY: 30,
}

stripe.api_key = settings.stripe_secret_key

# -----------------------------------------------------------------------------
# BUSINESS LOGIC --------------------------------------------------------------
# -----------------------------------------------------------------------------

# Inizializza una sottoscrizione interna di prova per il tenant.
async def crea_sottoscrizione_trial_tenant(
    db: AsyncSession,
    *,
    tenant_id: int,
    giorni_prova: int = GIORNI_PROVA_DEFAULT,
) -> Sottoscrizione:

    # Nessuna integrazione Stripe: il trial e' gestito solo via DB.

    risultato = await db.execute(
        select(Sottoscrizione)
        .where(Sottoscrizione.tenant_id == tenant_id)
        .limit(1)
    )

    sottoscrizione_esistente = risultato.scalar_one_or_none()
    if sottoscrizione_esistente is not None:
        return sottoscrizione_esistente


    fine_trial = datetime.now(timezone.utc) + timedelta(days=max(giorni_prova, 1))
    nuova_sottoscrizione = Sottoscrizione(
        tenant_id=tenant_id,
        piano=Sottoscrizioni.BASE,
        stato_piano=SottoscrizioniStati.PROVA,
        fine_periodo_corrente=fine_trial,
        id_stripe_cliente=None,
        id_stripe_sottoscrizione=None,
    )

    
    db.add(nuova_sottoscrizione)
    await db.flush()
    return nuova_sottoscrizione

# Definisce quanti utenti sono consentiti per piano.
def max_utenti_per_piano(piano: Sottoscrizioni) -> int:
    return LIMITI_UTENTI_PER_PIANO.get(piano, 1)


def stripe_configurato() -> bool:
    return bool(
        settings.stripe_secret_key
        and settings.stripe_price_base
        and settings.stripe_price_pro
        and settings.stripe_price_company
    )


def stripe_live_sync_configurato() -> bool:
    return bool(settings.stripe_secret_key)


def price_id_per_piano(piano: Sottoscrizioni) -> str | None:
    mapping = {
        Sottoscrizioni.BASE: settings.stripe_price_base,
        Sottoscrizioni.PRO: settings.stripe_price_pro,
        Sottoscrizioni.COMPANY: settings.stripe_price_company,
    }
    price_id = mapping.get(piano)
    return str(price_id) if price_id else None


def piano_da_price_id(price_id: str | None) -> Sottoscrizioni | None:
    if not price_id:
        return None
    mapping = {
        settings.stripe_price_base: Sottoscrizioni.BASE,
        settings.stripe_price_pro: Sottoscrizioni.PRO,
        settings.stripe_price_company: Sottoscrizioni.COMPANY,
    }
    return mapping.get(price_id)


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
    subscription_obj: dict[str, Any] | dict,
) -> bool:
    latest_invoice = subscription_obj.get("latest_invoice")
    if not isinstance(latest_invoice, dict):
        return False

    if latest_invoice.get("paid") is True:
        return True

    if str(latest_invoice.get("status") or "").strip().lower() == "paid":
        return True

    payment_intent = latest_invoice.get("payment_intent")
    if isinstance(payment_intent, dict):
        return str(payment_intent.get("status") or "").strip().lower() == "succeeded"

    return False


def datetime_da_unix(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalizza_data_utc(data: datetime | None) -> datetime | None:
    if data is None:
        return None
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def _calcola_scadenza_tregua(base: datetime | None = None) -> datetime:
    base_utc = _normalizza_data_utc(base) or datetime.now(timezone.utc)
    deadline = base_utc + timedelta(days=GIORNI_TREGUA_DISATTIVAZIONE)
    return deadline.replace(microsecond=TREGUA_MARKER_MICROSECOND)


def _e_scadenza_tregua(data: datetime | None) -> bool:
    data_utc = _normalizza_data_utc(data)
    if data_utc is None:
        return False
    return data_utc.microsecond == TREGUA_MARKER_MICROSECOND


def estrai_current_period_end_unix_da_subscription(
    subscription_obj: dict[str, Any] | dict,
) -> int | None:
    # Campo principale classico Stripe Subscription
    value = _to_int(subscription_obj.get("current_period_end"))
    if value is not None:
        return value

    # Fallback su eventuali varianti "current_period.end"
    current_period = subscription_obj.get("current_period") or {}
    if isinstance(current_period, dict):
        value = _to_int(current_period.get("end"))
        if value is not None:
            return value

    # Fallback su latest_invoice, utile in alcuni payload/eventi
    latest_invoice = subscription_obj.get("latest_invoice")
    if isinstance(latest_invoice, dict):
        value = _to_int(latest_invoice.get("period_end"))
        if value is not None:
            return value

        lines = (latest_invoice.get("lines") or {}).get("data") or []
        for line in lines:
            period = line.get("period") or {}
            value = _to_int(period.get("end"))
            if value is not None:
                return value

    return None


def _estrai_price_id_da_subscription(subscription_obj: dict[str, Any] | dict) -> str | None:
    items = (subscription_obj.get("items") or {}).get("data") or []
    if not items:
        return None
    price_obj = items[0].get("price") or {}
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


def _scegli_subscription_rilevante(subscriptions_obj: dict[str, Any] | dict) -> dict | None:
    data = subscriptions_obj.get("data") or []
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
) -> tuple[Sottoscrizione | None, bool, bool]:
    sottoscrizione = tenant_obj.sottoscrizione
    if not stripe_live_sync_configurato() or sottoscrizione is None:
        return sottoscrizione, False, False

    tenant_id = tenant_obj.id
    sub_obj = None
    cancel_at_period_end = False
    verifica_live_ok = False

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
            verifica_live_ok = True
        except stripe.error.InvalidRequestError as exc:
            if not _errore_stripe_subscription_inesistente(exc):
                await db.rollback()
                return tenant_obj.sottoscrizione, False, False
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
            await db.rollback()
            return tenant_obj.sottoscrizione, False, False

    if sub_obj is None:
        return tenant_obj.sottoscrizione, False, verifica_live_ok

    try:
        await sincronizza_sottoscrizione_da_stripe(
            db,
            tenant_id=tenant_id,
            stripe_subscription_id=str(sub_obj.get("id")),
            stripe_customer_id=str(sub_obj.get("customer")),
            stripe_status=stato_stripe_effettivo(
                str(sub_obj.get("status") or ""),
                invoice_paid=invoice_pagata_da_subscription_obj(sub_obj),
            ),
            stripe_price_id=_estrai_price_id_da_subscription(sub_obj),
            current_period_end_unix=estrai_current_period_end_unix_da_subscription(sub_obj),
        )
        await db.commit()
        cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end"))
    except Exception:
        await db.rollback()
        return tenant_obj.sottoscrizione, False, False

    return tenant_obj.sottoscrizione, cancel_at_period_end, verifica_live_ok


async def elimina_tenant_e_cascade(
    db: AsyncSession,
    *,
    tenant_id: int,
) -> None:
    risultato_utenti_primari = await db.execute(
        select(Utente).where(Utente.tenant_id == tenant_id)
    )
    utenti_primari = risultato_utenti_primari.scalars().all()
    utenti_primari_ids = [utente.id for utente in utenti_primari]

    utenti_condivisi_tenant_target: dict[int, int] = {}
    if utenti_primari_ids:
        risultato_ruoli_altri_tenant = await db.execute(
            select(UtenteRuoloTenant.utente_id, UtenteRuoloTenant.tenant_id)
            .where(
                UtenteRuoloTenant.utente_id.in_(utenti_primari_ids),
                UtenteRuoloTenant.tenant_id != tenant_id,
            )
            .order_by(
                UtenteRuoloTenant.utente_id.asc(),
                UtenteRuoloTenant.tenant_id.asc(),
            )
        )
        for utente_id, tenant_target_id in risultato_ruoli_altri_tenant.all():
            if utente_id not in utenti_condivisi_tenant_target:
                utenti_condivisi_tenant_target[utente_id] = int(tenant_target_id)

    utenti_da_eliminare_ids: list[int] = []
    for utente in utenti_primari:
        tenant_target_id = utenti_condivisi_tenant_target.get(utente.id)
        if tenant_target_id is None:
            utenti_da_eliminare_ids.append(utente.id)
            continue
        # Manteniamo l'account se e' gia' associato ad altri tenant.
        utente.tenant_id = tenant_target_id

    await db.execute(
        delete(UtenteRuoloTenant).where(UtenteRuoloTenant.tenant_id == tenant_id)
    )

    if utenti_da_eliminare_ids:
        await db.execute(
            delete(TokenResetPassword).where(
                TokenResetPassword.utente_id.in_(utenti_da_eliminare_ids)
            )
        )
        await db.execute(
            delete(UtenteRuoloTenant).where(
                UtenteRuoloTenant.utente_id.in_(utenti_da_eliminare_ids)
            )
        )
        await db.execute(delete(Utente).where(Utente.id.in_(utenti_da_eliminare_ids)))

    await db.execute(delete(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant_id))
    await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def applica_policy_disattivazione_tenant(
    db: AsyncSession,
    *,
    tenant_obj: Tenant,
) -> bool:
    """
    Policy:
    - stato ATTIVO/PROVA: nessuna cancellazione
    - stato SCADUTO/CANCELLATO: entra in SOSPESO per 14 giorni
    - stato SOSPESO: dopo 14 giorni, verifica live su Stripe e poi cancella in cascade
    """
    sottoscrizione = tenant_obj.sottoscrizione
    if sottoscrizione is None:
        return False

    # Safety check: prima di azioni distruttive, allinea sempre stato live da Stripe.
    sottoscrizione, _, verifica_live_ok = await sincronizza_sottoscrizione_tenant_live(
        db,
        tenant_obj=tenant_obj,
    )
    if sottoscrizione is None:
        return False
    ha_riferimenti_stripe = bool(
        sottoscrizione.id_stripe_sottoscrizione or sottoscrizione.id_stripe_cliente
    )
    if (
        ha_riferimenti_stripe
        and not verifica_live_ok
    ):
        # Fail-safe: se esistono riferimenti Stripe ma la verifica live non e' riuscita,
        # non applichiamo policy distruttive.
        return False

    stato = sottoscrizione.stato_piano
    if stato in {SottoscrizioniStati.ATTIVO, SottoscrizioniStati.PROVA}:
        return False

    adesso_utc = datetime.now(timezone.utc)
    fine_periodo_utc = _normalizza_data_utc(sottoscrizione.fine_periodo_corrente)

    if stato in {SottoscrizioniStati.SCADUTO, SottoscrizioniStati.CANCELLATO}:
        try:
            # Rilegge lo stato dopo la sync live per evitare transizioni stale
            # (es. webhook pagamento arrivato subito dopo la scadenza trial).
            await db.refresh(sottoscrizione)
        except Exception:
            await db.rollback()
            return False

        if sottoscrizione.stato_piano in {
            SottoscrizioniStati.ATTIVO,
            SottoscrizioniStati.PROVA,
        }:
            return False

        fine_periodo_utc = _normalizza_data_utc(sottoscrizione.fine_periodo_corrente)
        if fine_periodo_utc is None or fine_periodo_utc <= adesso_utc:
            sottoscrizione.stato_piano = SottoscrizioniStati.SOSPESO
            sottoscrizione.fine_periodo_corrente = _calcola_scadenza_tregua(adesso_utc)
            await db.commit()
        return False

    if stato == SottoscrizioniStati.SOSPESO:
        if fine_periodo_utc is None:
            sottoscrizione.fine_periodo_corrente = _calcola_scadenza_tregua(adesso_utc)
            await db.commit()
            return False

        if not _e_scadenza_tregua(fine_periodo_utc):
            # Hardening: se lo stato arriva da Stripe con una data non marcata
            # (es. fine periodo fatturazione), trasformiamo prima in vera tregua.
            if fine_periodo_utc <= adesso_utc:
                sottoscrizione.fine_periodo_corrente = _calcola_scadenza_tregua(adesso_utc)
                await db.commit()
            return False

        if fine_periodo_utc > adesso_utc:
            return False

        # Ultima verifica live su Stripe prima delete definitivo.
        sottoscrizione, _, verifica_live_ok = await sincronizza_sottoscrizione_tenant_live(
            db,
            tenant_obj=tenant_obj,
        )
        ha_riferimenti_stripe = bool(
            sottoscrizione
            and (sottoscrizione.id_stripe_sottoscrizione or sottoscrizione.id_stripe_cliente)
        )
        if (
            ha_riferimenti_stripe
            and not verifica_live_ok
        ):
            return False
        if (
            sottoscrizione is not None
            and sottoscrizione.stato_piano in {SottoscrizioniStati.ATTIVO, SottoscrizioniStati.PROVA}
        ):
            return False

        await elimina_tenant_e_cascade(
            db,
            tenant_id=tenant_obj.id,
        )
        await db.commit()
        return True

    return False


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
) -> Sottoscrizione | None:
    row = await trova_sottoscrizione_per_riferimenti(
        db,
        tenant_id=tenant_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
    )

    piano = piano_da_price_id(stripe_price_id) or Sottoscrizioni.BASE
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
        if (
            fine_periodo_utc <= adesso_utc
            and stato in {SottoscrizioniStati.ATTIVO, SottoscrizioniStati.PROVA}
        ):
            # Fallback locale: periodo concluso ma nessun rinnovo valido.
            if stato == SottoscrizioniStati.PROVA:
                stato = SottoscrizioniStati.SCADUTO
            else:
                stato = SottoscrizioniStati.SOSPESO
                fallback_grace_deadline = _calcola_scadenza_tregua(adesso_utc)

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
    elif stripe_status and stato != SottoscrizioniStati.SOSPESO:
        # Evita date stale (es. resta il vecchio "14 giorni trial" dopo passaggio a Stripe)
        row.fine_periodo_corrente = None
    if stripe_customer_id:
        row.id_stripe_cliente = stripe_customer_id
    if stripe_subscription_id:
        row.id_stripe_sottoscrizione = stripe_subscription_id
    await db.flush()
    return row
