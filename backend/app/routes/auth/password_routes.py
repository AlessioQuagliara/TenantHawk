# =============================================================================
# backend/app/routes/auth/password_routes.py
# =============================================================================

from __future__ import annotations

import secrets

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Response, status

from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import joinedload

from app.core import templates

from app.core.security.auth import prendi_utente_corrente

from app.core.infrastructure.database import get_db

from app.core.infrastructure.email import manda_reset_password

from app.core.security.sicurezza import hash_password, verifica_password_async

from app.models import TokenResetPassword, Utente

from .helpers import costruisci_url_assoluto

router = APIRouter()


@router.get("/password-recovery", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        "auth/forgot_password.html",
        {},
    )


@router.post("/password-recovery", response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera token reset password e invia email.

    Security: risposta sempre neutra per non rivelare se email esiste.
    """

    email_normalizzata = email.strip().lower()

    # Cerca utente
    risultato = await db.execute(
        select(Utente).where(
            Utente.email == email_normalizzata,
            Utente.attivo.is_(True),
        )
    )
    utente = risultato.scalar_one_or_none()

    if utente:
        # Genera token sicuro
        token = secrets.token_urlsafe(32)
        scadenza = datetime.now(timezone.utc) + timedelta(hours=1)  # Valido 1h

        # Salva token in DB
        token_reset = TokenResetPassword(
            utente_id=utente.id,
            token=token,
            scade_il=scadenza,
            usato=False,
        )
        db.add(token_reset)
        await db.commit()

        reset_link = costruisci_url_assoluto(f"/auth/reset-password?token={token}")

        background_tasks.add_task(manda_reset_password, email_normalizzata, reset_link)

    # Risposta sempre uguale (security)
    return templates.TemplateResponse(
        request,
        "auth/forgot_password.html",
        {
            "ok": "Se l'email esiste, riceverai un link di reset entro pochi minuti.",
        },
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Mostra form reset solo se token valido"""

    # Verifica token
    risultato = await db.execute(
        select(TokenResetPassword).where(
            TokenResetPassword.token == token,
            TokenResetPassword.usato.is_(False),
            TokenResetPassword.scade_il > datetime.now(timezone.utc),
        )
    )
    token_obj = risultato.scalar_one_or_none()

    if not token_obj:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {
                "error": "Token non valido o scaduto. Richiedi un nuovo reset.",
            },
            status_code=200,
        )

    return templates.TemplateResponse(
        request,
        "auth/reset_password.html",
        {"token": token},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Valida token e aggiorna password"""

    # Verifica password match
    if password != password2:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {
                "token": token,
                "error": "Le password non coincidono",
            },
            status_code=200,
        )

    # TODO: Valida complessità password
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {
                "token": token,
                "error": "Password troppo corta (minimo 8 caratteri)",
            },
            status_code=200,
        )

    # Trova token valido
    risultato = await db.execute(
        select(TokenResetPassword)
        .options(joinedload(TokenResetPassword.utente))
        .where(
            TokenResetPassword.token == token,
            TokenResetPassword.usato.is_(False),
            TokenResetPassword.scade_il > datetime.now(timezone.utc),
        )
    )
    token_obj = risultato.scalar_one_or_none()

    if not token_obj:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {
                "error": "Token non valido o scaduto",
            },
            status_code=200,
        )

    # Aggiorna password
    utente = token_obj.utente
    utente.hashed_password = hash_password(password)

    # Marca token come usato
    token_obj.usato = True

    await db.commit()

    # Redirect a login con messaggio successo
    return RedirectResponse(
        url="/auth/login?success=Password aggiornata con successo",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/confirm-password", response_class=HTMLResponse)
async def confirm_password_page(
    request: Request,
    next: str | None = None,
    error: str | None = None,
):
    """Pagina per conferma password"""
    return templates.TemplateResponse(
        request,
        "auth/confirm_password.html",
        {
            "next": next or "/",
            "error": error,
        },
    )


@router.post("/confirm-password", response_class=HTMLResponse)
async def confirm_password_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form("/"),
    db: AsyncSession = Depends(get_db),
    utente: Utente = Depends(prendi_utente_corrente),
):

    # Verifica password - Verifica password per azioni sensibili
    password_valida = await verifica_password_async(password, utente.hashed_password)

    if not password_valida:
        return templates.TemplateResponse(
            request,
            "auth/confirm_password.html",
            {
                "next": next,
                "error": "Password non corretta",
            },
            status_code=200,
        )

    # Se HTMX, redirect
    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.headers["HX-Redirect"] = next
        return risposta

    # Altrimenti redirect normale
    return RedirectResponse(
        url=next,
        status_code=status.HTTP_303_SEE_OTHER,
    )
