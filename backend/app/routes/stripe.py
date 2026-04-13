# =============================================================================
# backend/app/routes/stripe.py
# =============================================================================

from __future__ import annotations

import logging

from typing import Any

import stripe  # ty:ignore[unresolved-import]

from fastapi import APIRouter, Depends, HTTPException, Request, status

from starlette.concurrency import run_in_threadpool

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.billing import (
    estrai_current_period_end_unix_da_subscription,
    invoice_pagata_da_subscription_obj,
    piano_da_price_id,
    stato_stripe_effettivo,
    sincronizza_sottoscrizione_da_stripe,
)

from app.core.infrastructure.config import settings

from app.core.infrastructure.database import get_db

from app.core.infrastructure.email import manda_notifica_sottoscrizione

from app.models import Sottoscrizione, Tenant, Utente, UtenteRuolo, UtenteRuoloTenant

router = APIRouter(prefix="/stripe", tags=["stripe"])

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key


def _stripe_obj_to_dict(value: Any) -> dict[str, Any]:
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


def _clean_stripe_id(value: Any) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    if value_str.lower() in {"none", "null", "undefined"}:
        return None
    return value_str


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _price_id_from_subscription_obj(subscription_obj: Any) -> str | None:
    subscription_data = _stripe_obj_to_dict(subscription_obj)
    items = (_stripe_obj_to_dict(subscription_data.get("items")).get("data")) or []
    if not items:
        return None
    price_obj = _stripe_obj_to_dict(_stripe_obj_to_dict(items[0]).get("price"))
    price_id = price_obj.get("id")
    return str(price_id) if price_id else None


def _tenant_id_from_subscription_obj(subscription_obj: Any) -> int | None:
    subscription_data = _stripe_obj_to_dict(subscription_obj)
    metadata = _stripe_obj_to_dict(subscription_data.get("metadata"))
    return _to_int(metadata.get("tenant_id"))


def _payment_status_da_subscription_obj(subscription_obj: Any) -> str | None:
    subscription_data = _stripe_obj_to_dict(subscription_obj)
    stato_subscription = str(subscription_data.get("status") or "").strip().lower()
    if stato_subscription in {"active", "trialing"}:
        return "paid"
    if invoice_pagata_da_subscription_obj(subscription_obj):
        return "paid"
    return None


async def _sync_from_subscription(
    db: AsyncSession,
    *,
    subscription_obj: Any,
    tenant_id: int | None = None,
    status_override: str | None = None,
    payment_status: str | None = None,
    invoice_paid: bool = False,
) -> Sottoscrizione | None:
    subscription_data = _stripe_obj_to_dict(subscription_obj)
    latest_invoice = _stripe_obj_to_dict(subscription_data.get("latest_invoice"))
    ultimo_pagamento_ok = (
        True
        if invoice_paid
        else (invoice_pagata_da_subscription_obj(subscription_data) if latest_invoice else None)
    )
    return await sincronizza_sottoscrizione_da_stripe(
        db,
        tenant_id=tenant_id,
        stripe_subscription_id=_clean_stripe_id(subscription_data.get("id")),
        stripe_customer_id=_clean_stripe_id(subscription_data.get("customer")),
        stripe_status=stato_stripe_effettivo(
            status_override or str(subscription_data.get("status") or ""),
            payment_status=payment_status,
            invoice_paid=invoice_paid,
        ),
        stripe_price_id=_price_id_from_subscription_obj(subscription_data),
        current_period_end_unix=estrai_current_period_end_unix_da_subscription(
            subscription_data
        ),
        ultimo_pagamento_ok=ultimo_pagamento_ok,
    )


async def _sync_from_subscription_id(
    db: AsyncSession,
    *,
    subscription_id: str,
    tenant_id: int | None = None,
    status_override: str | None = None,
    payment_status: str | None = None,
    invoice_paid: bool = False,
) -> Sottoscrizione | None:
    subscription_obj = stripe.Subscription.retrieve(
        subscription_id,
        expand=[
            "items.data.price",
            "latest_invoice",
            "latest_invoice.lines.data",
            "latest_invoice.payment_intent",
        ],
    )
    subscription_obj = _stripe_obj_to_dict(subscription_obj)
    payment_status_effettivo = payment_status or _payment_status_da_subscription_obj(
        subscription_obj
    )
    invoice_paid_effettivo = invoice_paid or invoice_pagata_da_subscription_obj(
        subscription_obj
    )
    tenant_id_effettivo = tenant_id or _tenant_id_from_subscription_obj(subscription_obj)
    return await _sync_from_subscription(
        db,
        subscription_obj=subscription_obj,
        tenant_id=tenant_id_effettivo,
        status_override=status_override,
        payment_status=payment_status_effettivo,
        invoice_paid=invoice_paid_effettivo,
    )


async def _sync_from_invoice_id(
    db: AsyncSession,
    *,
    invoice_id: str,
    status_override: str | None = None,
    payment_status: str | None = None,
    invoice_paid: bool = False,
) -> Sottoscrizione | None:
    invoice_obj = stripe.Invoice.retrieve(invoice_id)
    invoice_obj = _stripe_obj_to_dict(invoice_obj)
    subscription_id = _clean_stripe_id(invoice_obj.get("subscription"))
    if not subscription_id:
        return None
    return await _sync_from_subscription_id(
        db,
        subscription_id=subscription_id,
        status_override=status_override,
        payment_status=payment_status,
        invoice_paid=invoice_paid,
    )


async def _destinatari_notifica_tenant(
    db: AsyncSession,
    *,
    tenant_id: int,
) -> tuple[str, list[str]]:
    risultato_tenant = await db.execute(
        select(Tenant.nome).where(Tenant.id == tenant_id).limit(1)
    )
    nome_tenant = risultato_tenant.scalar_one_or_none() or f"Tenant #{tenant_id}"

    risultato_superutenti = await db.execute(
        select(Utente.email)
        .join(UtenteRuoloTenant, UtenteRuoloTenant.utente_id == Utente.id)
        .where(
            UtenteRuoloTenant.tenant_id == tenant_id,
            UtenteRuoloTenant.ruolo == UtenteRuolo.SUPERUTENTE,
            Utente.attivo.is_(True),
        )
    )
    destinatari = sorted(
        {
            str(email).strip().lower()
            for email in risultato_superutenti.scalars().all()
            if email
        }
    )
    return str(nome_tenant), destinatari


def _descrivi_operazione_evento(
    event_type: str,
    *,
    data_obj: Any,
) -> tuple[str | None, str | None]:
    data = _stripe_obj_to_dict(data_obj)
    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return (
            "Checkout completato",
            "Il checkout Stripe e' stato completato correttamente.",
        )
    if event_type == "customer.subscription.created":
        return "Sottoscrizione attivata", "Stripe ha creato una nuova sottoscrizione."
    if event_type == "customer.subscription.deleted":
        return "Sottoscrizione cancellata", "La sottoscrizione risulta terminata su Stripe."
    if event_type == "customer.subscription.updated":
        if bool(data.get("cancel_at_period_end")):
            return (
                "Annullamento a fine periodo impostato",
                "Il rinnovo automatico e' disattivato: il piano termina a fine periodo.",
            )
        return "Sottoscrizione aggiornata", "Stripe ha aggiornato i dettagli del piano."
    if event_type in {"invoice.paid", "invoice.payment_succeeded"}:
        return "Pagamento riuscito", "Pagamento registrato con successo."
    if event_type == "invoice.payment_failed":
        return (
            "Pagamento non riuscito",
            "Stripe non e' riuscito ad addebitare il rinnovo.",
        )
    if event_type == "checkout.session.async_payment_failed":
        return (
            "Pagamento checkout non riuscito",
            "Il pagamento asincrono del checkout non e' andato a buon fine.",
        )
    return None, None


async def _notifica_evento_abbonamento(
    db: AsyncSession,
    *,
    event_type: str,
    data_obj: dict[str, Any],
    sottoscrizione_snapshot: dict[str, Any] | None,
) -> None:
    if sottoscrizione_snapshot is None:
        return

    operazione, dettagli = _descrivi_operazione_evento(
        event_type,
        data_obj=data_obj,
    )
    if operazione is None:
        return

    nome_tenant, destinatari = await _destinatari_notifica_tenant(
        db,
        tenant_id=int(sottoscrizione_snapshot["tenant_id"]),
    )
    if not destinatari:
        return

    stato = str(sottoscrizione_snapshot.get("stato") or "n/d")
    piano = str(sottoscrizione_snapshot.get("piano") or "n/d")

    if not piano or piano == "base":
        # Fallback su Stripe data quando il mapping non e' ancora consolidato.
        stripe_price = None
        if event_type.startswith("customer.subscription."):
            stripe_price = _price_id_from_subscription_obj(data_obj)
        if stripe_price:
            piano_mappato = piano_da_price_id(stripe_price)
            if piano_mappato is not None:
                piano = piano_mappato.value

    for destinatario in destinatari:
        try:
            await run_in_threadpool(
                manda_notifica_sottoscrizione,
                destinatario,
                nome_tenant,
                operazione,
                stato,
                piano,
                dettagli,
            )
        except Exception:
            logger.exception(
                "Errore invio email evento subscription. tenant_id=%s destinatario=%s event=%s",
                sottoscrizione_snapshot["tenant_id"],
                destinatario,
                event_type,
            )


def _snapshot_sottoscrizione(
    sottoscrizione: Sottoscrizione | None,
) -> dict[str, Any] | None:
    if sottoscrizione is None:
        return None
    return {
        "tenant_id": int(sottoscrizione.tenant_id),
        "stato": sottoscrizione.stato_piano.value,
        "piano": sottoscrizione.piano.value,
    }


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret non configurato",
        )

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.stripe_webhook_secret,
        )
    except ValueError as exc:
        logger.warning("Stripe webhook payload non valido: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload webhook non valido") from exc
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("Stripe webhook firma non valida: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Firma webhook non valida") from exc

    event_data = _stripe_obj_to_dict(event)
    event_type = str(event_data.get("type") or "")
    event_payload = _stripe_obj_to_dict(event_data.get("data"))
    data_obj = _stripe_obj_to_dict(event_payload.get("object"))
    logger.info("Stripe webhook ricevuto: event=%s id=%s", event_type, event_data.get("id"))

    try:
        sincronizzato = False
        sottoscrizione_sincronizzata: Sottoscrizione | None = None
        snapshot_notifica: dict[str, Any] | None = None
        if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
            if data_obj.get("mode") == "subscription" and data_obj.get("subscription"):
                metadata = _stripe_obj_to_dict(data_obj.get("metadata"))
                tenant_id = _to_int(metadata.get("tenant_id"))
                status_override = None
                if str(data_obj.get("payment_status") or "").lower() == "paid":
                    status_override = "active"
                subscription_id = _clean_stripe_id(data_obj.get("subscription"))
                if not subscription_id:
                    logger.warning(
                        "Webhook %s senza subscription id valido",
                        event_type,
                    )
                    await db.commit()
                    return {"received": True}
                sottoscrizione_sincronizzata = await _sync_from_subscription_id(
                    db,
                    subscription_id=subscription_id,
                    tenant_id=tenant_id,
                    status_override=status_override,
                    payment_status=str(data_obj.get("payment_status") or ""),
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        elif event_type == "checkout.session.async_payment_failed":
            if data_obj.get("mode") == "subscription" and data_obj.get("subscription"):
                metadata = _stripe_obj_to_dict(data_obj.get("metadata"))
                tenant_id = _to_int(metadata.get("tenant_id"))
                subscription_id = _clean_stripe_id(data_obj.get("subscription"))
                if not subscription_id:
                    logger.warning(
                        "Webhook %s senza subscription id valido",
                        event_type,
                    )
                    await db.commit()
                    return {"received": True}
                sottoscrizione_sincronizzata = await _sync_from_subscription_id(
                    db,
                    subscription_id=subscription_id,
                    tenant_id=tenant_id,
                    status_override="past_due",
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        elif event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "customer.subscription.paused",
            "customer.subscription.resumed",
        }:
            metadata = _stripe_obj_to_dict(data_obj.get("metadata"))
            tenant_id = _to_int(metadata.get("tenant_id"))
            subscription_id = _clean_stripe_id(data_obj.get("id")) or ""
            if not subscription_id:
                logger.warning(
                    "Webhook %s senza subscription id: impossibile sync affidabile da payload",
                    event_type,
                )
            else:
                sottoscrizione_sincronizzata = await _sync_from_subscription_id(
                    db,
                    subscription_id=subscription_id,
                    tenant_id=tenant_id,
                    payment_status=_payment_status_da_subscription_obj(data_obj),
                    invoice_paid=invoice_pagata_da_subscription_obj(data_obj),
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        elif event_type in {"invoice.paid", "invoice.payment_succeeded"}:
            subscription_id = _clean_stripe_id(data_obj.get("subscription"))
            if subscription_id:
                sottoscrizione_sincronizzata = await _sync_from_subscription_id(
                    db,
                    subscription_id=subscription_id,
                    payment_status=str(data_obj.get("payment_status") or ""),
                    invoice_paid=True,
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        elif event_type == "invoice.payment_failed":
            subscription_id = _clean_stripe_id(data_obj.get("subscription"))
            if subscription_id:
                sottoscrizione_sincronizzata = await _sync_from_subscription_id(
                    db,
                    subscription_id=subscription_id,
                    status_override="past_due",
                    payment_status=str(data_obj.get("payment_status") or ""),
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        elif event_type == "payment_intent.succeeded":
            invoice_id = _clean_stripe_id(data_obj.get("invoice"))
            if invoice_id:
                sottoscrizione_sincronizzata = await _sync_from_invoice_id(
                    db,
                    invoice_id=invoice_id,
                    payment_status="paid",
                    invoice_paid=True,
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        elif event_type in {"charge.succeeded", "charge.updated"}:
            invoice_id = _clean_stripe_id(data_obj.get("invoice"))
            if invoice_id:
                sottoscrizione_sincronizzata = await _sync_from_invoice_id(
                    db,
                    invoice_id=invoice_id,
                    payment_status="paid",
                    invoice_paid=True,
                )
                snapshot_notifica = _snapshot_sottoscrizione(sottoscrizione_sincronizzata)
                sincronizzato = True

        await db.commit()
        if sincronizzato:
            await _notifica_evento_abbonamento(
                db,
                event_type=event_type,
                data_obj=data_obj,
                sottoscrizione_snapshot=snapshot_notifica,
            )
        logger.info(
            "Stripe webhook processato: event=%s sincronizzato=%s",
            event_type,
            sincronizzato,
        )
    except Exception:
        await db.rollback()
        logger.exception("Errore gestione webhook Stripe (event_type=%s)", event_type)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Errore interno gestione webhook Stripe",
        )

    return {"received": True}
