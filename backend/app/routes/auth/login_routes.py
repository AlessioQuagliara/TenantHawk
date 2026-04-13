# =============================================================================
# backend/app/routes/auth/login_routes.py
# =============================================================================

from __future__ import annotations

import logging

from urllib.parse import quote_plus

from itsdangerous import BadSignature, SignatureExpired

from fastapi import APIRouter, Depends, Form, Request, Response, status

from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy import func, select

from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.security.auth import SESSION_COOKIE_NAME

from app.core.security.csrf import csrf_protezione

from app.core.infrastructure.database import get_db

from app.core.security.sessione import gestore_sessioni

from app.core.security.sicurezza import verifica_password_async

from app.models import Utente

from .helpers import (
    SELEZIONE_TENANT_MAX_AGE_SECONDI,
    contesto_login,
    contesto_selezione_tenant,
    estrai_slug_tenant_da_next,
    serializer_selezione_tenant_login,
)
from .session_utils import crea_risposta_login_ok
from .tenant_access import carica_tenant_accessibili_utente

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: str | None = None,
    error: str | None = None,
    success: str | None = None,
):
    """Pagina login con token CSRF"""
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        contesto_login(
            next_path=next or "/",
            errore=error,
            success=success,
        ),
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    sessione_temp: str = Form(...),
    next_path: str = Form("/", alias="next"),
    db: AsyncSession = Depends(get_db),
):
    """Login con CSRF e sessione Redis"""
    email_normalizzata = email.strip().lower()

    # ---- Verifica CSRF --------------------------------------
    if not csrf_protezione.valida_token(sessione_temp, csrf_token):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            contesto_login(
                next_path=next_path,
                errore="Token CSRF non valido",
            ),
            status_code=200,
        )

    try:
        # ---- Trova utente ---------------------------------------
        risultato = await db.execute(
            select(Utente).where(
                func.lower(Utente.email) == email_normalizzata,
            )
        )

        utente = risultato.scalar_one_or_none()

        # ---- Verifica password ASYNC ----------------------------
        password_valida = False
        if utente:
            password_valida = await verifica_password_async(password, utente.hashed_password)

        if not utente or not password_valida:
            return templates.TemplateResponse(
                request,
                "auth/login.html",
                contesto_login(
                    next_path=next_path,
                    errore="Credenziali non valide",
                ),
                status_code=200,
            )

        if not utente.attivo:
            return templates.TemplateResponse(
                request,
                "auth/login.html",
                contesto_login(
                    next_path=next_path,
                    errore="Account non attivo. Controlla l'email di conferma.",
                ),
                status_code=200,
            )

        # ---- Carica tenant accessibili ---------------------------------------
        slug_tenant_next = estrai_slug_tenant_da_next(next_path)
        tenant_candidati = await carica_tenant_accessibili_utente(db, utente.id)
    except ProgrammingError:
        logger.exception("Login fallito: schema DB non pronto (email=%s)", email_normalizzata)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            contesto_login(
                next_path=next_path,
                errore="Database non inizializzato. Esegui le migrazioni e riprova.",
            ),
            status_code=200,
        )
    except SQLAlchemyError:
        logger.exception(
            "Login fallito: errore database inatteso (email=%s)",
            email_normalizzata,
        )
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            contesto_login(
                next_path=next_path,
                errore="Errore temporaneo del servizio. Riprova tra poco.",
            ),
            status_code=200,
        )

    if not tenant_candidati:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            contesto_login(
                next_path=next_path,
                errore="Nessun tenant disponibile per questo account.",
            ),
            status_code=200,
        )

    if len(tenant_candidati) > 1:
        token_selezione = serializer_selezione_tenant_login.dumps(
            {"id_utente": utente.id, "next": next_path}
        )
        tenant_selezionato_slug = None
        if slug_tenant_next:
            tenant_selezionato_slug = next(
                (
                    tenant_item.slug
                    for tenant_item in tenant_candidati
                    if tenant_item.slug == slug_tenant_next
                ),
                None,
            )
        if tenant_selezionato_slug is None:
            tenant_selezionato_slug = next(
                (
                    tenant_item.slug
                    for tenant_item in tenant_candidati
                    if tenant_item.id == utente.tenant_id
                ),
                None,
            )
        return templates.TemplateResponse(
            request,
            "auth/select_tenant.html",
            contesto_selezione_tenant(
                token_selezione=token_selezione,
                tenant_candidati=tenant_candidati,
                tenant_selezionato_slug=tenant_selezionato_slug,
                email_utente=utente.email,
                next_path=next_path,
            ),
            status_code=200,
        )

    return await crea_risposta_login_ok(
        request,
        utente=utente,
        tenant=tenant_candidati[0],
        next_path=next_path,
    )


@router.post("/select-tenant", response_class=HTMLResponse)
async def select_tenant_submit(
    request: Request,
    token_selezione: str = Form(...),
    tenant_slug: str = Form(...),
    csrf_token: str = Form(...),
    sessione_temp: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = serializer_selezione_tenant_login.loads(
            token_selezione,
            max_age=SELEZIONE_TENANT_MAX_AGE_SECONDI,
        )
    except SignatureExpired:
        errore = quote_plus("La selezione tenant è scaduta. Effettua di nuovo il login.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except BadSignature:
        errore = quote_plus("Token selezione tenant non valido.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    id_utente = payload.get("id_utente")
    next_path = str(payload.get("next") or "/")
    if not id_utente:
        errore = quote_plus("Sessione di login non valida. Riprova.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    risultato_utente = await db.execute(
        select(Utente).where(
            Utente.id == int(id_utente),
            Utente.attivo.is_(True),
        )
    )
    utente = risultato_utente.scalar_one_or_none()
    if utente is None:
        errore = quote_plus("Utente non disponibile. Effettua di nuovo il login.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    tenant_candidati = await carica_tenant_accessibili_utente(db, utente.id)
    if not tenant_candidati:
        errore = quote_plus("Nessun tenant disponibile per questo account.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not csrf_protezione.valida_token(sessione_temp, csrf_token):
        return templates.TemplateResponse(
            request,
            "auth/select_tenant.html",
            contesto_selezione_tenant(
                token_selezione=token_selezione,
                tenant_candidati=tenant_candidati,
                tenant_selezionato_slug=tenant_slug,
                email_utente=utente.email,
                next_path=next_path,
                errore="Token CSRF non valido",
            ),
            status_code=200,
        )

    tenant = next(
        (tenant_item for tenant_item in tenant_candidati if tenant_item.slug == tenant_slug),
        None,
    )
    if tenant is None:
        return templates.TemplateResponse(
            request,
            "auth/select_tenant.html",
            contesto_selezione_tenant(
                token_selezione=token_selezione,
                tenant_candidati=tenant_candidati,
                tenant_selezionato_slug=tenant_slug,
                email_utente=utente.email,
                next_path=next_path,
                errore="Seleziona un tenant valido.",
            ),
            status_code=200,
        )

    return await crea_risposta_login_ok(
        request,
        utente=utente,
        tenant=tenant,
        next_path=next_path,
    )


@router.post("/logout")
async def logout_submit(
    request: Request,
):
    """Logout idempotente: cancella sessione se presente e rimanda al login."""
    id_sessione_utente = request.cookies.get(SESSION_COOKIE_NAME)

    if id_sessione_utente:
        await gestore_sessioni.cancella_sessione(id_sessione_utente)

    risposta = RedirectResponse(
        url="/auth/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    risposta.delete_cookie(SESSION_COOKIE_NAME)

    return risposta
