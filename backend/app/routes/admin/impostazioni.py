# =============================================================================
# backend/app/routes/admin/impostazioni.py
# =============================================================================

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, status

from fastapi.responses import HTMLResponse, RedirectResponse

from pydantic import ValidationError

from sqlalchemy import select

from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.security.auth import prendi_utente_corrente

from app.core.infrastructure.database import get_db

from app.core.security.permessi import prendi_ruolo_corrente

from app.core.security.sicurezza import hash_password, verifica_password_async

from app.core.tenancy import prendi_tenant_con_accesso

from app.models import Tenant, Utente

from app.schemas.impostazioni import (
    ImpostazioniPasswordAggiornamento,
    ImpostazioniProfiloAggiornamento,
)

from .template_context import giorni_rimasti_trial_da_sottoscrizione

router = APIRouter()

# -----------------------------------------------------------------------------
# IMPOSTAZIONI ----------------------------------------------------------------
# -----------------------------------------------------------------------------


def _normalizza_nome(nome: str) -> str:
    return " ".join(nome.strip().split())


def _redirect_impostazioni(
    tenant_slug: str,
    *,
    ok: str | None = None,
    errore: str | None = None,
) -> RedirectResponse:
    params: dict[str, str] = {}
    if ok:
        params["ok"] = ok
    if errore:
        params["errore"] = errore

    url = f"/{tenant_slug}/admin/impostazioni"
    if params:
        url = f"{url}?{urlencode(params)}"

    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/impostazioni", response_class=HTMLResponse)
async def impostazioni_page(
    request: Request,
    ok: str | None = None,
    errore: str | None = None,
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    ruolo_corrente: str = Depends(prendi_ruolo_corrente),
):
    return templates.TemplateResponse(
        request,
        "admin/impostazioni/index.html",
        {
            "tenant": tenant_obj,
            "utente": utente_corrente,
            "ruolo_corrente": ruolo_corrente,
            "giorni_rimasti_trial": giorni_rimasti_trial_da_sottoscrizione(
                tenant_obj.sottoscrizione
            ),
            "ok": ok,
            "errore": errore,
        },
    )


@router.post("/impostazioni/profilo")
async def aggiorna_profilo_submit(
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    nome: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    nome_normalizzato = _normalizza_nome(nome)
    email_normalizzata = email.strip().lower()

    try:
        payload = ImpostazioniProfiloAggiornamento(
            nome=nome_normalizzato,
            email=email_normalizzata,
        )
    except ValidationError:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Inserisci un indirizzo email valido.",
        )

    if len(payload.nome) < 2:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Il nome deve contenere almeno 2 caratteri.",
        )
    if len(payload.nome) > 255:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Il nome supera la lunghezza massima consentita.",
        )

    if email_normalizzata != utente_corrente.email:
        email_esistente = await db.execute(
            select(Utente.id).where(
                Utente.email == email_normalizzata,
                Utente.id != utente_corrente.id,
            )
        )
        if email_esistente.scalar_one_or_none():
            return _redirect_impostazioni(
                tenant_obj.slug,
                errore="Questa email è già associata a un altro account.",
            )

    modificato = False
    if utente_corrente.nome != payload.nome:
        utente_corrente.nome = payload.nome
        modificato = True
    if utente_corrente.email != email_normalizzata:
        utente_corrente.email = email_normalizzata
        modificato = True

    if not modificato:
        return _redirect_impostazioni(
            tenant_obj.slug,
            ok="Nessuna modifica da salvare.",
        )

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Errore temporaneo durante il salvataggio del profilo.",
        )

    return _redirect_impostazioni(
        tenant_obj.slug,
        ok="Profilo aggiornato con successo.",
    )


@router.post("/impostazioni/password")
async def aggiorna_password_submit(
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    password_attuale: str = Form(...),
    password_nuova: str = Form(...),
    password_nuova_conferma: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    payload = ImpostazioniPasswordAggiornamento(
        password_attuale=password_attuale,
        password_nuova=password_nuova,
        password_nuova_conferma=password_nuova_conferma,
    )

    if not payload.password_attuale or not payload.password_nuova:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Compila tutti i campi password.",
        )
    if payload.password_nuova != payload.password_nuova_conferma:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Le nuove password non coincidono.",
        )
    if len(payload.password_nuova) < 8:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="La nuova password deve avere almeno 8 caratteri.",
        )
    if payload.password_attuale == payload.password_nuova:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="La nuova password deve essere diversa da quella attuale.",
        )

    password_attuale_valida = await verifica_password_async(
        payload.password_attuale,
        utente_corrente.hashed_password,
    )
    if not password_attuale_valida:
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Password attuale non corretta.",
        )

    utente_corrente.hashed_password = hash_password(payload.password_nuova)
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        return _redirect_impostazioni(
            tenant_obj.slug,
            errore="Errore temporaneo durante il cambio password.",
        )

    return _redirect_impostazioni(
        tenant_obj.slug,
        ok="Password aggiornata con successo.",
    )
