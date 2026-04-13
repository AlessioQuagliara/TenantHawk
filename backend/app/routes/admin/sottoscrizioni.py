# =============================================================================
# backend/app/routes/admin/sottoscrizioni.py
# =============================================================================

from __future__ import annotations

import logging

import math

from datetime import datetime, timezone

from typing import Any

from urllib.parse import quote_plus

import stripe  # ty:ignore[unresolved-import]

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, status

from fastapi.responses import HTMLResponse, RedirectResponse, Response

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.security.auth import prendi_utente_corrente

from app.core.billing import (
    estrai_current_period_end_unix_da_subscription,
    invoice_pagata_da_subscription_obj,
    price_id_per_piano,
    stato_stripe_effettivo,
    sincronizza_sottoscrizione_da_stripe,
    sincronizza_sottoscrizione_tenant_live,
    stripe_configurato,
)

from app.core.infrastructure.config import settings

from app.core.infrastructure.database import get_db

from app.core.infrastructure.email import manda_notifica_sottoscrizione

from app.core.security.permessi import prendi_ruolo_corrente, richiede_ruolo

from app.core.tenancy import prendi_tenant_corrente

from app.models import Sottoscrizioni, Tenant, Utente, UtenteRuolo

from .template_context import giorni_rimasti_trial_da_sottoscrizione

router = APIRouter()
logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key

# -----------------------------------------------------------------------------
# NORMALIZZATORI --------------------------------------------------------------
# -----------------------------------------------------------------------------

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


def _normalizza_data_utc(data: datetime) -> datetime:
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def _giorni_rimanenti(fine_periodo: datetime | None) -> int | None:
    if fine_periodo is None:
        return None
    adesso_utc = datetime.now(timezone.utc)
    fine_periodo_utc = _normalizza_data_utc(fine_periodo)
    secondi = (fine_periodo_utc - adesso_utc).total_seconds()
    if secondi <= 0:
        return 0
    return int(math.ceil(secondi / 86400))


def _sottoscrizioni_base_url(tenant_slug: str) -> str:
    return f"/{tenant_slug}/admin/sottoscrizioni"


def _gestisci_base_url(tenant_slug: str) -> str:
    return f"/{tenant_slug}/admin/sottoscrizioni/gestisci"


def _redirect_sottoscrizioni(
    tenant_slug: str,
    *,
    ok: str | None = None,
    errore: str | None = None,
) -> RedirectResponse:
    url = _sottoscrizioni_base_url(tenant_slug)
    if ok:
        url = f"{url}?ok={quote_plus(ok)}"
    if errore:
        url = f"{url}?errore={quote_plus(errore)}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _redirect_gestisci(
    tenant_slug: str,
    *,
    ok: str | None = None,
    errore: str | None = None,
) -> RedirectResponse:
    url = _gestisci_base_url(tenant_slug)
    if ok:
        url = f"{url}?ok={quote_plus(ok)}"
    if errore:
        url = f"{url}?errore={quote_plus(errore)}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _estrai_price_id_da_subscription(subscription_obj: dict) -> str | None:
    subscription_data = _stripe_obj_to_dict(subscription_obj)
    items = (_stripe_obj_to_dict(subscription_data.get("items")).get("data")) or []
    if not items:
        return None
    first_item = _stripe_obj_to_dict(items[0])
    price_obj = _stripe_obj_to_dict(first_item.get("price"))
    return str(price_obj.get("id")) if price_obj.get("id") else None


def _estrai_item_id_da_subscription(subscription_obj: dict) -> str | None:
    subscription_data = _stripe_obj_to_dict(subscription_obj)
    items = (_stripe_obj_to_dict(subscription_data.get("items")).get("data")) or []
    if not items:
        return None
    item_id = _stripe_obj_to_dict(items[0]).get("id")
    return str(item_id) if item_id else None


def _estrai_current_period_end(subscription_obj: dict) -> int | None:
    return estrai_current_period_end_unix_da_subscription(subscription_obj)


def _estrai_subscription_id_da_checkout_session(checkout_session_obj: dict) -> str | None:
    checkout_data = _stripe_obj_to_dict(checkout_session_obj)
    subscription = checkout_data.get("subscription")
    if isinstance(subscription, str):
        return subscription
    if isinstance(subscription, dict):
        sub_id = subscription.get("id")
        return str(sub_id) if sub_id else None
    return str(subscription) if subscription else None


def _url_assoluto(percorso_relativo: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}{percorso_relativo}"


def _accoda_notifica_abbonamento(
    background_tasks: BackgroundTasks,
    *,
    destinatario: str,
    nome_tenant: str,
    operazione: str,
    stato: str | None = None,
    piano: str | None = None,
    dettagli: str | None = None,
) -> None:
    if not destinatario:
        return
    background_tasks.add_task(
        manda_notifica_sottoscrizione,
        destinatario,
        nome_tenant,
        operazione,
        stato,
        piano,
        dettagli,
    )


def _errore_stripe_customer_inesistente(exc: Exception) -> bool:
    if not isinstance(exc, stripe.error.InvalidRequestError):
        return False
    code = str(getattr(exc, "code", "")).lower()
    message = str(exc).lower()
    return "no such customer" in message or (
        code == "resource_missing" and "customer" in message
    )


def _errore_stripe_subscription_inesistente(exc: Exception) -> bool:
    if not isinstance(exc, stripe.error.InvalidRequestError):
        return False
    code = str(getattr(exc, "code", "")).lower()
    message = str(exc).lower()
    return "no such subscription" in message or (
        code == "resource_missing" and "subscription" in message
    )


def _errore_portale_non_configurato(exc: Exception) -> bool:
    if not isinstance(exc, stripe.error.InvalidRequestError):
        return False
    message = str(exc).lower()
    return "billing portal" in message and "configuration" in message


async def _assicurati_cliente_stripe(
    *,
    tenant_obj: Tenant,
    utente_corrente: Utente,
    db: AsyncSession,
    forza_nuovo: bool = False,
) -> str:
    sottoscrizione = tenant_obj.sottoscrizione
    customer_id_attuale = (
        _clean_stripe_id(sottoscrizione.id_stripe_cliente)
        if sottoscrizione is not None
        else None
    )
    if (
        sottoscrizione
        and customer_id_attuale
        and not forza_nuovo
    ):
        return customer_id_attuale

    customer = stripe.Customer.create(
        email=utente_corrente.email,
        name=tenant_obj.nome,
        metadata={
            "tenant_id": str(tenant_obj.id),
            "tenant_slug": tenant_obj.slug,
        },
    )
    customer = _stripe_obj_to_dict(customer)
    customer_id = _clean_stripe_id(customer.get("id"))
    if not customer_id:
        raise RuntimeError("Stripe Customer.create non ha restituito un customer id valido")

    if sottoscrizione is not None:
        sottoscrizione.id_stripe_cliente = customer_id
        await db.commit()

    return customer_id


# -----------------------------------------------------------------------------
# SOTTOSCRIZIONI ----------------------------------------------------------------
# -----------------------------------------------------------------------------


@router.get("/sottoscrizioni", response_class=HTMLResponse)
async def sottoscrizioni_page(
    request: Request,
    ok: str | None = None,
    errore: str | None = None,
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    ruolo_corrente: str = Depends(prendi_ruolo_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    sottoscrizione, cancel_at_period_end, sync_live_ok, live_details = await sincronizza_sottoscrizione_tenant_live(
        db,
        tenant_obj=tenant_obj,
    )
    stato_piano = sottoscrizione.stato_piano.value if sottoscrizione else None
    piano = sottoscrizione.piano.value if sottoscrizione else None
    fine_periodo = sottoscrizione.fine_periodo_corrente if sottoscrizione else None
    if fine_periodo is None and live_details is not None:
        current_period_end_unix = _to_int(live_details.get("current_period_end_unix"))
        if current_period_end_unix is not None:
            fine_periodo = datetime.fromtimestamp(current_period_end_unix, tz=timezone.utc)
    stripe_customer_id = (
        _clean_stripe_id(sottoscrizione.id_stripe_cliente)
        if sottoscrizione is not None
        else None
    )
    stripe_subscription_id = (
        _clean_stripe_id(sottoscrizione.id_stripe_sottoscrizione)
        if sottoscrizione is not None
        else None
    )
    ultimo_pagamento_ok = (
        bool(live_details["ultimo_pagamento_ok"])
        if live_details is not None and live_details.get("ultimo_pagamento_ok") is not None
        else (
            bool(sottoscrizione.ultimo_pagamento_ok)
            if sottoscrizione is not None and sottoscrizione.ultimo_pagamento_ok is not None
            else None
        )
    )
    giorni_rimanenti_raw = _giorni_rimanenti(fine_periodo)  # ty:ignore[invalid-argument-type]
    periodo_in_aggiornamento = bool(
        stato_piano == "attivo"
        and fine_periodo is not None
        and giorni_rimanenti_raw == 0
        and not cancel_at_period_end
    )
    giorni_rimanenti = None if periodo_in_aggiornamento else giorni_rimanenti_raw

    return templates.TemplateResponse(
        request,
        "admin/sottoscrizioni/index.html",
        {
            "tenant": tenant_obj,
            "utente": utente_corrente,
            "ruolo_corrente": ruolo_corrente,
            "sottoscrizione": sottoscrizione,
            "stato_piano": stato_piano,
            "piano": piano,
            "fine_periodo": fine_periodo,
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "in_tregua": stato_piano == "sospeso" and fine_periodo is not None,
            "sync_live_ok": sync_live_ok,
            "ha_pagato_ultimo_rinnovo": ultimo_pagamento_ok,
            "giorni_rimanenti": giorni_rimanenti,
            "giorni_rimasti_trial": giorni_rimasti_trial_da_sottoscrizione(
                sottoscrizione
            ),
            "periodo_in_aggiornamento": periodo_in_aggiornamento,
            "is_trial": stato_piano == "prova",
            "is_attivo": stato_piano == "attivo",
            "is_sospeso": stato_piano == "sospeso",
            "is_scaduto": stato_piano == "scaduto",
            "is_cancellato": stato_piano == "cancellato",
            "trial_in_scadenza": (
                stato_piano == "prova"
                and giorni_rimanenti is not None
                and 0 < giorni_rimanenti <= 3
            ),
            "trial_scaduto": stato_piano == "prova" and giorni_rimanenti == 0,
            "cancel_at_period_end": cancel_at_period_end,
            "ok": ok,
            "errore": errore,
        },
    )


@router.get("/sottoscrizioni/gestisci", response_class=HTMLResponse)
async def sottoscrizioni_gestisci_page(
    request: Request,
    ok: str | None = None,
    errore: str | None = None,
    stripe_session_id: str | None = None,
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    ruolo_corrente: str = Depends(prendi_ruolo_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    sottoscrizione = tenant_obj.sottoscrizione
    stripe_enabled = stripe_configurato()

    if stripe_enabled and stripe_session_id:
        try:
            checkout_session = stripe.checkout.Session.retrieve(
                stripe_session_id,
                expand=["subscription"],
            )
            checkout_session = _stripe_obj_to_dict(checkout_session)
            subscription_id = _estrai_subscription_id_da_checkout_session(checkout_session)
            if subscription_id:
                sub_obj = stripe.Subscription.retrieve(
                    subscription_id,
                    expand=[
                        "items.data.price",
                        "latest_invoice",
                        "latest_invoice.lines.data",
                        "latest_invoice.payment_intent",
                    ],
                )
                sub_obj = _stripe_obj_to_dict(sub_obj)
                status_effettivo = stato_stripe_effettivo(
                    str(sub_obj.get("status") or ""),
                    payment_status=str(checkout_session.get("payment_status") or ""),
                    invoice_paid=invoice_pagata_da_subscription_obj(sub_obj),
                )
                latest_invoice = _stripe_obj_to_dict(sub_obj.get("latest_invoice"))
                ultimo_pagamento_ok = (
                    invoice_pagata_da_subscription_obj(sub_obj)
                    if latest_invoice
                    else None
                )
                await sincronizza_sottoscrizione_da_stripe(
                    db,
                    tenant_id=tenant_obj.id,
                    stripe_subscription_id=_clean_stripe_id(sub_obj.get("id")),
                    stripe_customer_id=_clean_stripe_id(sub_obj.get("customer")),
                    stripe_status=status_effettivo,
                    stripe_price_id=_estrai_price_id_da_subscription(sub_obj),
                    current_period_end_unix=_estrai_current_period_end(sub_obj),
                    ultimo_pagamento_ok=ultimo_pagamento_ok,
                )
                await db.commit()
                sottoscrizione = tenant_obj.sottoscrizione
                if not ok:
                    ok = "Sottoscrizione sincronizzata correttamente."
        except Exception:
            await db.rollback()
            if not errore:
                errore = (
                    "Checkout completato, sincronizzazione in differita tramite webhook."
                )

    cancel_at_period_end = False
    if stripe_enabled:
        sottoscrizione, cancel_at_period_end, _, _ = await sincronizza_sottoscrizione_tenant_live(
            db,
            tenant_obj=tenant_obj,
        )

    piani = [
        {
            "key": Sottoscrizioni.BASE.value,
            "label": "Base",
            "price_id": price_id_per_piano(Sottoscrizioni.BASE),
        },
        {
            "key": Sottoscrizioni.PRO.value,
            "label": "Pro",
            "price_id": price_id_per_piano(Sottoscrizioni.PRO),
        },
        {
            "key": Sottoscrizioni.COMPANY.value,
            "label": "Company",
            "price_id": price_id_per_piano(Sottoscrizioni.COMPANY),
        },
    ]

    piano_corrente = sottoscrizione.piano.value if sottoscrizione else None
    stato_piano = sottoscrizione.stato_piano.value if sottoscrizione else None
    is_trial = stato_piano == "prova"
    stripe_subscription_id = (
        _clean_stripe_id(sottoscrizione.id_stripe_sottoscrizione)
        if sottoscrizione is not None
        else None
    )
    ha_sottoscrizione_stripe = bool(
        sottoscrizione and stripe_subscription_id
    )

    return templates.TemplateResponse(
        request,
        "admin/sottoscrizioni/gestisci.html",
        {
            "tenant": tenant_obj,
            "utente": utente_corrente,
            "ruolo_corrente": ruolo_corrente,
            "sottoscrizione": sottoscrizione,
            "stripe_enabled": stripe_enabled,
            "piani": piani,
            "piano_corrente": piano_corrente,
            "stato_piano": stato_piano,
            "is_trial": is_trial,
            "ha_sottoscrizione_stripe": ha_sottoscrizione_stripe,
            "giorni_rimasti_trial": giorni_rimasti_trial_da_sottoscrizione(
                sottoscrizione
            ),
            "cancel_at_period_end": cancel_at_period_end,
            "ok": ok,
            "errore": errore,
        },
    )


@router.post("/sottoscrizioni/gestisci/piano")
async def sottoscrizioni_cambia_piano_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    piano: str = Form(...),
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    tenant_slug = tenant_obj.slug
    tenant_id = tenant_obj.id
    tenant_nome = tenant_obj.nome

    if not stripe_configurato():
        return _redirect_gestisci(
            tenant_slug,
            errore="Stripe non configurato correttamente.",
        )

    try:
        piano_enum = Sottoscrizioni(piano)
    except ValueError:
        return _redirect_gestisci(
            tenant_slug,
            errore="Piano non valido.",
        )

    price_id = price_id_per_piano(piano_enum)
    if not price_id:
        return _redirect_gestisci(
            tenant_slug,
            errore="Price ID non configurato per il piano selezionato.",
        )

    sottoscrizione = tenant_obj.sottoscrizione
    if sottoscrizione is None:
        return _redirect_sottoscrizioni(
            tenant_slug,
            errore="Sottoscrizione tenant non trovata.",
        )
    stripe_subscription_id = _clean_stripe_id(sottoscrizione.id_stripe_sottoscrizione)

    customer_id = await _assicurati_cliente_stripe(
        tenant_obj=tenant_obj,
        utente_corrente=utente_corrente,
        db=db,
    )

    try:
        deve_aprire_checkout = not bool(stripe_subscription_id)
        if not deve_aprire_checkout:
            try:
                subscription_obj = stripe.Subscription.retrieve(
                    str(stripe_subscription_id),
                    expand=[
                        "items.data.price",
                        "latest_invoice",
                        "latest_invoice.lines.data",
                        "latest_invoice.payment_intent",
                    ],
                )
                subscription_obj = _stripe_obj_to_dict(subscription_obj)
                stato_corrente = str(subscription_obj.get("status") or "")
                if stato_corrente in {"canceled", "incomplete_expired"}:
                    deve_aprire_checkout = True
            except stripe.error.InvalidRequestError as exc:
                if not _errore_stripe_subscription_inesistente(exc):
                    raise
                sottoscrizione.id_stripe_sottoscrizione = None
                await db.commit()
                stripe_subscription_id = None
                deve_aprire_checkout = True

        if not deve_aprire_checkout:
            item_id = _estrai_item_id_da_subscription(subscription_obj)
            if not item_id:
                return _redirect_gestisci(
                    tenant_slug,
                    errore="Impossibile aggiornare il piano: item subscription non trovato.",
                )

            updated = stripe.Subscription.modify(
                str(stripe_subscription_id),
                cancel_at_period_end=False,
                proration_behavior="create_prorations",
                items=[{"id": item_id, "price": price_id}],
            )
            updated = _stripe_obj_to_dict(updated)
            invoice_paid_flag = invoice_pagata_da_subscription_obj(updated)
            latest_invoice = _stripe_obj_to_dict(updated.get("latest_invoice"))
            ultimo_pagamento_ok = invoice_paid_flag if latest_invoice else None
            status_effettivo = stato_stripe_effettivo(
                str(updated.get("status") or ""),
                invoice_paid=invoice_paid_flag,
            )
            await sincronizza_sottoscrizione_da_stripe(
                db,
                tenant_id=tenant_id,
                stripe_subscription_id=_clean_stripe_id(updated.get("id")),
                stripe_customer_id=_clean_stripe_id(updated.get("customer")),
                stripe_status=status_effettivo,
                stripe_price_id=_estrai_price_id_da_subscription(updated),
                current_period_end_unix=_estrai_current_period_end(updated),
                ultimo_pagamento_ok=ultimo_pagamento_ok,
            )
            await db.commit()
            _accoda_notifica_abbonamento(
                background_tasks,
                destinatario=utente_corrente.email,
                nome_tenant=tenant_nome,
                operazione="Cambio piano applicato",
                stato=str(updated.get("status") or ""),
                piano=piano_enum.value,
                dettagli="Il piano è stato aggiornato con effetto immediato.",
            )
            return _redirect_gestisci(
                tenant_slug,
                ok="Piano aggiornato correttamente.",
            )

        success_url = _url_assoluto(_gestisci_base_url(tenant_slug))
        cancel_url = _url_assoluto(_gestisci_base_url(tenant_slug))
        success_url = (
            f"{success_url}?ok={quote_plus('Checkout completato, sincronizzazione in corso.')}"
            "&stripe_session_id={CHECKOUT_SESSION_ID}"
        )
        cancel_url = f"{cancel_url}?errore={quote_plus('Checkout annullato.')}"

        try:
            checkout_session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"tenant_id": str(tenant_id)},
                subscription_data={
                    "metadata": {"tenant_id": str(tenant_id)},
                },
            )
            checkout_session = _stripe_obj_to_dict(checkout_session)
        except stripe.error.InvalidRequestError as exc:
            if not _errore_stripe_customer_inesistente(exc):
                raise
            customer_id = await _assicurati_cliente_stripe(
                tenant_obj=tenant_obj,
                utente_corrente=utente_corrente,
                db=db,
                forza_nuovo=True,
            )
            checkout_session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"tenant_id": str(tenant_id)},
                subscription_data={
                    "metadata": {"tenant_id": str(tenant_id)},
                },
            )
            checkout_session = _stripe_obj_to_dict(checkout_session)
    except Exception:
        logger.exception(
            "Errore Stripe checkout/cambio piano. tenant=%s piano=%s customer_id=%s",
            tenant_slug,
            piano_enum.value,
            customer_id,
        )
        await db.rollback()
        return _redirect_gestisci(
            tenant_slug,
            errore="Errore Stripe durante l'avvio checkout/cambio piano.",
        )

    url_checkout = checkout_session.get("url")
    if not url_checkout:
        return _redirect_gestisci(
            tenant_slug,
            errore="Checkout URL non disponibile.",
        )
    _accoda_notifica_abbonamento(
        background_tasks,
        destinatario=utente_corrente.email,
        nome_tenant=tenant_nome,
        operazione="Checkout avviato",
        stato="in elaborazione",
        piano=piano_enum.value,
        dettagli="È stato avviato il checkout Stripe per cambio/attivazione piano.",
    )
    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.headers["HX-Redirect"] = str(url_checkout)
        return risposta
    return RedirectResponse(url=str(url_checkout), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sottoscrizioni/gestisci/portal")
async def sottoscrizioni_portal_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    tenant_slug = tenant_obj.slug

    if not stripe_configurato():
        return _redirect_gestisci(
            tenant_slug,
            errore="Stripe non configurato correttamente.",
        )

    sottoscrizione = tenant_obj.sottoscrizione
    if sottoscrizione is None:
        return _redirect_sottoscrizioni(
            tenant_slug,
            errore="Sottoscrizione tenant non trovata.",
        )
    stato_notifica = (
        sottoscrizione.stato_piano.value
        if getattr(sottoscrizione, "stato_piano", None) is not None
        else "n/d"
    )
    piano_notifica = (
        sottoscrizione.piano.value
        if getattr(sottoscrizione, "piano", None) is not None
        else "n/d"
    )

    customer_id = await _assicurati_cliente_stripe(
        tenant_obj=tenant_obj,
        utente_corrente=utente_corrente,
        db=db,
    )

    try:
        try:
            sessione_portale = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=_url_assoluto(_gestisci_base_url(tenant_slug)),
            )
            sessione_portale = _stripe_obj_to_dict(sessione_portale)
        except stripe.error.InvalidRequestError as exc:
            if not _errore_stripe_customer_inesistente(exc):
                raise
            logger.warning(
                "Customer Stripe non trovato in portal_submit. tenant=%s customer_id=%s err=%s",
                tenant_slug,
                customer_id,
                exc,
            )
            customer_id = await _assicurati_cliente_stripe(
                tenant_obj=tenant_obj,
                utente_corrente=utente_corrente,
                db=db,
                forza_nuovo=True,
            )
            sessione_portale = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=_url_assoluto(_gestisci_base_url(tenant_slug)),
            )
            sessione_portale = _stripe_obj_to_dict(sessione_portale)
    except stripe.error.InvalidRequestError as exc:
        logger.warning(
            "Errore Stripe apertura Billing Portal. tenant=%s customer_id=%s err=%s",
            tenant_slug,
            customer_id,
            exc,
        )
        if _errore_portale_non_configurato(exc):
            return _redirect_gestisci(
                tenant_slug,
                errore=(
                    "Billing Portal non configurato su Stripe. "
                    "Abilitalo dalla Dashboard Stripe."
                ),
            )
        return _redirect_gestisci(
            tenant_slug,
            errore="Impossibile aprire il portale Stripe.",
        )
    except Exception:
        logger.exception(
            "Errore inatteso apertura Billing Portal. tenant=%s customer_id=%s",
            tenant_slug,
            customer_id,
        )
        return _redirect_gestisci(
            tenant_slug,
            errore="Impossibile aprire il portale Stripe.",
        )

    portal_url = sessione_portale.get("url")
    if not portal_url:
        return _redirect_gestisci(
            tenant_slug,
            errore="Portale Stripe non disponibile.",
        )
    _accoda_notifica_abbonamento(
        background_tasks,
        destinatario=utente_corrente.email,
        nome_tenant=tenant_obj.nome,
        operazione="Accesso Billing Portal",
        stato=stato_notifica,
        piano=piano_notifica,
        dettagli="È stato richiesto l'accesso al Billing Portal Stripe.",
    )
    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.headers["HX-Redirect"] = str(portal_url)
        return risposta
    return RedirectResponse(url=str(portal_url), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sottoscrizioni/gestisci/annulla")
async def sottoscrizioni_annulla_submit(
    background_tasks: BackgroundTasks,
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    tenant_slug = tenant_obj.slug
    tenant_id = tenant_obj.id

    if not stripe_configurato():
        return _redirect_gestisci(
            tenant_slug,
            errore="Stripe non configurato correttamente.",
        )

    sottoscrizione = tenant_obj.sottoscrizione
    stripe_subscription_id = (
        _clean_stripe_id(sottoscrizione.id_stripe_sottoscrizione)
        if sottoscrizione is not None
        else None
    )
    if sottoscrizione is None or not stripe_subscription_id:
        return _redirect_gestisci(
            tenant_slug,
            errore="Nessuna sottoscrizione Stripe da annullare.",
        )
    piano_notifica = (
        sottoscrizione.piano.value
        if getattr(sottoscrizione, "piano", None) is not None
        else "n/d"
    )

    try:
        updated = stripe.Subscription.modify(
            str(stripe_subscription_id),
            cancel_at_period_end=True,
        )
        updated = _stripe_obj_to_dict(updated)
        status_effettivo = stato_stripe_effettivo(
            str(updated.get("status") or ""),
            invoice_paid=invoice_pagata_da_subscription_obj(updated),
        )
        latest_invoice = _stripe_obj_to_dict(updated.get("latest_invoice"))
        ultimo_pagamento_ok = (
            invoice_pagata_da_subscription_obj(updated)
            if latest_invoice
            else None
        )
        await sincronizza_sottoscrizione_da_stripe(
            db,
            tenant_id=tenant_id,
            stripe_subscription_id=_clean_stripe_id(updated.get("id")),
            stripe_customer_id=_clean_stripe_id(updated.get("customer")),
            stripe_status=status_effettivo,
            stripe_price_id=_estrai_price_id_da_subscription(updated),
            current_period_end_unix=_estrai_current_period_end(updated),
            ultimo_pagamento_ok=ultimo_pagamento_ok,
        )
        await db.commit()
    except stripe.error.InvalidRequestError as exc:
        await db.rollback()
        if _errore_stripe_subscription_inesistente(exc):
            try:
                sottoscrizione.id_stripe_sottoscrizione = None
                await db.commit()
            except Exception:
                await db.rollback()
            return _redirect_gestisci(
                tenant_slug,
                errore=(
                    "La sottoscrizione Stripe non risulta più esistente. "
                    "Seleziona un piano per riallineare il tenant."
                ),
            )
        logger.warning(
            "Errore Stripe annullamento a fine periodo. tenant=%s sub_id=%s err=%s",
            tenant_slug,
            stripe_subscription_id,
            exc,
        )
        return _redirect_gestisci(
            tenant_slug,
            errore="Errore Stripe durante l'annullamento del piano.",
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "Errore inatteso annullamento a fine periodo. tenant=%s sub_id=%s",
            tenant_slug,
            stripe_subscription_id,
        )
        return _redirect_gestisci(
            tenant_slug,
            errore="Errore durante l'annullamento del piano.",
        )

    _accoda_notifica_abbonamento(
        background_tasks,
        destinatario=utente_corrente.email,
        nome_tenant=tenant_obj.nome,
        operazione="Annullamento a fine periodo richiesto",
        stato=str(updated.get("status") or ""),
        piano=piano_notifica,
        dettagli="Il rinnovo automatico è stato disattivato.",
    )
    return _redirect_gestisci(
        tenant_slug,
        ok="Piano impostato per annullamento a fine periodo.",
    )


@router.post("/sottoscrizioni/gestisci/riattiva")
async def sottoscrizioni_riattiva_submit(
    background_tasks: BackgroundTasks,
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    tenant_slug = tenant_obj.slug
    tenant_id = tenant_obj.id

    if not stripe_configurato():
        return _redirect_gestisci(
            tenant_slug,
            errore="Stripe non configurato correttamente.",
        )

    sottoscrizione = tenant_obj.sottoscrizione
    stripe_subscription_id = (
        _clean_stripe_id(sottoscrizione.id_stripe_sottoscrizione)
        if sottoscrizione is not None
        else None
    )
    if sottoscrizione is None or not stripe_subscription_id:
        return _redirect_gestisci(
            tenant_slug,
            errore="Nessuna sottoscrizione Stripe da riattivare.",
        )
    piano_notifica = (
        sottoscrizione.piano.value
        if getattr(sottoscrizione, "piano", None) is not None
        else "n/d"
    )

    try:
        updated = stripe.Subscription.modify(
            str(stripe_subscription_id),
            cancel_at_period_end=False,
        )
        updated = _stripe_obj_to_dict(updated)
        status_effettivo = stato_stripe_effettivo(
            str(updated.get("status") or ""),
            invoice_paid=invoice_pagata_da_subscription_obj(updated),
        )
        latest_invoice = _stripe_obj_to_dict(updated.get("latest_invoice"))
        ultimo_pagamento_ok = (
            invoice_pagata_da_subscription_obj(updated)
            if latest_invoice
            else None
        )
        await sincronizza_sottoscrizione_da_stripe(
            db,
            tenant_id=tenant_id,
            stripe_subscription_id=_clean_stripe_id(updated.get("id")),
            stripe_customer_id=_clean_stripe_id(updated.get("customer")),
            stripe_status=status_effettivo,
            stripe_price_id=_estrai_price_id_da_subscription(updated),
            current_period_end_unix=_estrai_current_period_end(updated),
            ultimo_pagamento_ok=ultimo_pagamento_ok,
        )
        await db.commit()
    except stripe.error.InvalidRequestError as exc:
        await db.rollback()
        if _errore_stripe_subscription_inesistente(exc):
            try:
                sottoscrizione.id_stripe_sottoscrizione = None
                await db.commit()
            except Exception:
                await db.rollback()
            return _redirect_gestisci(
                tenant_slug,
                errore=(
                    "La sottoscrizione Stripe non risulta più esistente. "
                    "Seleziona un piano per riallineare il tenant."
                ),
            )
        logger.warning(
            "Errore Stripe riattivazione rinnovo. tenant=%s sub_id=%s err=%s",
            tenant_slug,
            stripe_subscription_id,
            exc,
        )
        return _redirect_gestisci(
            tenant_slug,
            errore="Errore Stripe durante la riattivazione del piano.",
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "Errore inatteso riattivazione rinnovo. tenant=%s sub_id=%s",
            tenant_slug,
            stripe_subscription_id,
        )
        return _redirect_gestisci(
            tenant_slug,
            errore="Errore durante la riattivazione del piano.",
        )

    _accoda_notifica_abbonamento(
        background_tasks,
        destinatario=utente_corrente.email,
        nome_tenant=tenant_obj.nome,
        operazione="Riattivazione rinnovo automatico",
        stato=str(updated.get("status") or ""),
        piano=piano_notifica,
        dettagli="Il rinnovo automatico è stato riattivato.",
    )
    return _redirect_gestisci(
        tenant_slug,
        ok="Annullamento rimosso: il piano continuerà a rinnovarsi.",
    )
