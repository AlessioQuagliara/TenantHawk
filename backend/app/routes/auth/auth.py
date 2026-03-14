# =============================================================================
# backend/app/routes/auth/auth.py
# =============================================================================

from __future__ import annotations

import logging

import re

import secrets

from datetime import datetime, timedelta, timezone

from urllib.parse import quote_plus

from unicodedata import normalize

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.models import TokenResetPassword

from fastapi import APIRouter, Form, Request, status, Depends, HTTPException, Response, BackgroundTasks

from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy import select

from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

from sqlalchemy.orm import joinedload

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.database import get_db

from app.core.sicurezza import verifica_password_async, hash_password

from app.core.sessione import gestore_sessioni

from app.core.config import settings

from app.core.csrf import csrf_protezione

from app.core.auth import prendi_utente_corrente

from app.models import Utente, Tenant, UtenteRuoloTenant, UtenteRuolo

from app.core.email import manda_conferma_account, manda_reset_password

logger = logging.getLogger(__name__)

router = APIRouter()

serializer_conferma_account = URLSafeTimedSerializer(
    settings.secret_key,
    salt="conferma-account",
)

# -----------------------------------------------------------------------------
# NORMALIZZATORI TESTO PER SANIFICAZIONE
# -----------------------------------------------------------------------------


def normalizza_slug_tenant(testo: str) -> str:
    """
    Converte un testo libero in slug URL-safe:
    - minuscolo
    - rimozione accenti
    - caratteri non validi -> '-'
    """
    testo_ascii = normalize("NFKD", testo).encode("ascii", "ignore").decode("ascii")
    testo_minuscolo = testo_ascii.lower().strip()
    testo_slug = re.sub(r"[^a-z0-9]+", "-", testo_minuscolo)
    testo_slug = re.sub(r"-{2,}", "-", testo_slug).strip("-")
    return testo_slug


def nuovo_csrf_form() -> tuple[str, str]:
    sessione_temporanea = secrets.token_urlsafe(16)
    token_csrf = csrf_protezione.genera_token(sessione_temporanea)
    return sessione_temporanea, token_csrf


def contesto_registrazione(
    request: Request,
    *,
    nome_tenant: str = "",
    slug_tenant: str = "",
    nome_utente: str = "",
    email: str = "",
    errore: str | None = None,
) -> dict[str, str | Request | None]:
    sessione_temporanea, token_csrf = nuovo_csrf_form()
    return {
        "request": request,
        "nome_tenant": nome_tenant,
        "slug_tenant": slug_tenant,
        "nome_utente": nome_utente,
        "email": email,
        "error": errore,
        "csrf_token": token_csrf,
        "sessione_temp": sessione_temporanea,
    }


def costruisci_url_assoluto(percorso: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/{percorso.lstrip('/')}"


# -----------------------------------------------------------------------------
# LOGIN - GET
# -----------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: str | None = None,
    error: str | None = None,
    success: str | None = None,
):
    """Pagina login con token CSRF"""
    # Genera sessione temporanea per CSRF
    sessione_temp = secrets.token_urlsafe(16)
    csrf_token = csrf_protezione.genera_token(sessione_temp)
    
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "next": next or "/",
            "error": error,
            "success": success,
            "csrf_token": csrf_token,
            "sessione_temp": sessione_temp,
        },
    )


# -----------------------------------------------------------------------------
# LOGIN - POST
# -----------------------------------------------------------------------------

@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    sessione_temp: str = Form(...),
    next: str = Form("/"),
    db: AsyncSession = Depends(get_db),
):
    """Login con CSRF e sessione Redis"""
    
    # ---- Verifica CSRF --------------------------------------
    if not csrf_protezione.valida_token(sessione_temp, csrf_token):
        nuova_sessione_temp = secrets.token_urlsafe(16)
        nuovo_csrf = csrf_protezione.genera_token(nuova_sessione_temp)
        
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "next": next,
                "error": "Token CSRF non valido",
                "csrf_token": nuovo_csrf,
                "sessione_temp": nuova_sessione_temp,
            },
            status_code=200,
        )
    
    try:
        # ---- Trova utente ---------------------------------------
        risultato = await db.execute(
            select(Utente).where(
                Utente.email == email,
            )
        )
        
        utente = risultato.scalar_one_or_none()
        
        # ---- Verifica password ASYNC ----------------------------
        password_valida = False
        if utente:
            password_valida = await verifica_password_async(password, utente.hashed_password)
        
        if not utente or not password_valida:
            nuova_sessione_temp = secrets.token_urlsafe(16)
            nuovo_csrf = csrf_protezione.genera_token(nuova_sessione_temp)
            
            return templates.TemplateResponse(
                "auth/login.html",
                {
                    "request": request,
                    "next": next,
                    "error": "Credenziali non valide",
                    "csrf_token": nuovo_csrf,
                    "sessione_temp": nuova_sessione_temp,
                },
                status_code=200,
            )

        if not utente.attivo:
            nuova_sessione_temp = secrets.token_urlsafe(16)
            nuovo_csrf = csrf_protezione.genera_token(nuova_sessione_temp)
            return templates.TemplateResponse(
                "auth/login.html",
                {
                    "request": request,
                    "next": next,
                    "error": "Account non attivo. Controlla l'email di conferma.",
                    "csrf_token": nuovo_csrf,
                    "sessione_temp": nuova_sessione_temp,
                },
                status_code=200,
            )
        
        # ---- Verifica tenant ------------------------------------
        risultato_tenant = await db.execute(
            select(Tenant).where(
                Tenant.id == utente.tenant_id,
                Tenant.attivo.is_(True),
            )
        )
        
        tenant = risultato_tenant.scalar_one_or_none()
    except ProgrammingError:
        logger.exception("Login fallito: schema DB non pronto (email=%s)", email)
        nuova_sessione_temp = secrets.token_urlsafe(16)
        nuovo_csrf = csrf_protezione.genera_token(nuova_sessione_temp)
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "next": next,
                "error": "Database non inizializzato. Esegui le migrazioni e riprova.",
                "csrf_token": nuovo_csrf,
                "sessione_temp": nuova_sessione_temp,
            },
            status_code=200,
        )
    except SQLAlchemyError:
        logger.exception("Login fallito: errore database inatteso (email=%s)", email)
        nuova_sessione_temp = secrets.token_urlsafe(16)
        nuovo_csrf = csrf_protezione.genera_token(nuova_sessione_temp)
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "next": next,
                "error": "Errore temporaneo del servizio. Riprova tra poco.",
                "csrf_token": nuovo_csrf,
                "sessione_temp": nuova_sessione_temp,
            },
            status_code=200,
        )
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant non disponibile",
        )
    
    # ---- Crea sessione Redis --------------------------------
    id_sessione_utente = await gestore_sessioni.crea_sessione(
        id_utente=utente.id,
        id_tenant=tenant.id,
        email=utente.email,
    )
    
    # ---- Redirect -------------------------------------------
    redirect_url = (
        next
        if next and next != "/"
        else f"/{tenant.slug}/admin/dashboard"
    )
    
    # HTMX
    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.set_cookie(
            "id_sessione_utente",
            id_sessione_utente,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=86400,
        )
        risposta.headers["HX-Redirect"] = redirect_url
        return risposta
    
    # Normale
    risposta = RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    
    risposta.set_cookie(
        "id_sessione_utente",
        id_sessione_utente,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=86400,
    )
    
    return risposta


# -----------------------------------------------------------------------------
# LOGOUT
# -----------------------------------------------------------------------------

@router.post("/logout")
async def logout_submit(
    request: Request,
    utente: Utente = Depends(prendi_utente_corrente),
):
    """Logout con cancellazione sessione Redis"""
    id_sessione_utente = request.cookies.get("id_sessione_utente")
    
    if id_sessione_utente:
        await gestore_sessioni.cancella_sessione(id_sessione_utente)
    
    risposta = RedirectResponse(
        url="/auth/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    risposta.delete_cookie("id_sessione_utente")
    
    return risposta


# -----------------------------------------------------------------------------
# SIGN-UP (registrazione) - GET
# -----------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        "auth/register.html",
        contesto_registrazione(request),
    )

# -----------------------------------------------------------------------------
# SIGN-UP (registrazione) - POST
# -----------------------------------------------------------------------------

@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    nome_tenant: str = Form(...),
    slug_tenant: str = Form(""),
    nome_utente: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    conferma_password: str = Form(...),
    csrf_token: str = Form(...),
    sessione_temp: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    nome_tenant = nome_tenant.strip()
    slug_tenant = slug_tenant.strip()
    nome_utente = nome_utente.strip()
    email = email.strip().lower()

    if not csrf_protezione.valida_token(sessione_temp, csrf_token):
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant,
                nome_utente=nome_utente,
                email=email,
                errore="Token CSRF non valido",
            ),
            status_code=200,
        )

    if not nome_tenant:
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant,
                nome_utente=nome_utente,
                email=email,
                errore="Il nome tenant è obbligatorio",
            ),
            status_code=200,
        )

    if not email:
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant,
                nome_utente=nome_utente,
                email=email,
                errore="L'email è obbligatoria",
            ),
            status_code=200,
        )

    if password != conferma_password:
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant,
                nome_utente=nome_utente,
                email=email,
                errore="Le password non coincidono",
            ),
            status_code=200,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant,
                nome_utente=nome_utente,
                email=email,
                errore="Password troppo corta (minimo 8 caratteri)",
            ),
            status_code=200,
        )

    slug_tenant_finale = normalizza_slug_tenant(slug_tenant or nome_tenant)
    if not slug_tenant_finale:
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant,
                nome_utente=nome_utente,
                email=email,
                errore="Slug tenant non valido",
            ),
            status_code=200,
        )

    try:
        risultato_tenant = await db.execute(
            select(Tenant).where(Tenant.slug == slug_tenant_finale)
        )
        tenant_esistente = risultato_tenant.scalar_one_or_none()
        if tenant_esistente:
            return templates.TemplateResponse(
                "auth/register.html",
                contesto_registrazione(
                    request,
                    nome_tenant=nome_tenant,
                    slug_tenant=slug_tenant_finale,
                    nome_utente=nome_utente,
                    email=email,
                    errore="Slug tenant già in uso",
                ),
                status_code=200,
            )

        risultato_utente = await db.execute(
            select(Utente).where(Utente.email == email)
        )
        utente_esistente = risultato_utente.scalar_one_or_none()
        if utente_esistente:
            return templates.TemplateResponse(
                "auth/register.html",
                contesto_registrazione(
                    request,
                    nome_tenant=nome_tenant,
                    slug_tenant=slug_tenant_finale,
                    nome_utente=nome_utente,
                    email=email,
                    errore="Email già registrata",
                ),
                status_code=200,
            )

        nuovo_tenant = Tenant(
            slug=slug_tenant_finale,
            nome=nome_tenant,
            attivo=True,
        )
        db.add(nuovo_tenant)
        await db.flush()

        nuovo_utente = Utente(
            tenant_id=nuovo_tenant.id,
            nome=nome_utente or None,
            email=email,
            hashed_password=hash_password(password),
            attivo=False,
        )
        db.add(nuovo_utente)
        await db.flush()

        ruolo_tenant = UtenteRuoloTenant(
            utente_id=nuovo_utente.id,
            tenant_id=nuovo_tenant.id,
            # Chi si registra creando il tenant è il proprietario iniziale.
            ruolo=UtenteRuolo.SUPERUTENTE,
        )
        db.add(ruolo_tenant)
        await db.commit()

        token_conferma = serializer_conferma_account.dumps(
            {"id_utente": nuovo_utente.id, "email": nuovo_utente.email}
        )
        link_conferma = costruisci_url_assoluto(
            f"/auth/confirm-account?token={token_conferma}"
        )
        background_tasks.add_task(
            manda_conferma_account,
            nuovo_utente.email,
            link_conferma,
            nome_tenant,
        )
    except ProgrammingError:
        await db.rollback()
        logger.exception("Registrazione fallita: schema DB non pronto (email=%s)", email)
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant_finale,
                nome_utente=nome_utente,
                email=email,
                errore="Database non inizializzato. Esegui le migrazioni e riprova.",
            ),
            status_code=200,
        )
    except IntegrityError:
        await db.rollback()
        logger.exception("Registrazione fallita: vincolo DB violato (email=%s)", email)
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant_finale,
                nome_utente=nome_utente,
                email=email,
                errore="Email o slug tenant già in uso",
            ),
            status_code=200,
        )
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Registrazione fallita: errore database inatteso (email=%s)", email)
        return templates.TemplateResponse(
            "auth/register.html",
            contesto_registrazione(
                request,
                nome_tenant=nome_tenant,
                slug_tenant=slug_tenant_finale,
                nome_utente=nome_utente,
                email=email,
                errore="Errore temporaneo del servizio. Riprova tra poco.",
            ),
            status_code=200,
        )

    messaggio_successo = quote_plus(
        "Registrazione completata. Controlla la tua email per confermare l'account."
    )
    url_redirect = f"/auth/login?success={messaggio_successo}"

    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.headers["HX-Redirect"] = url_redirect
        return risposta

    return RedirectResponse(url=url_redirect, status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# CONFERMA ACCOUNT - GET
# -----------------------------------------------------------------------------

@router.get("/confirm-account")
async def confirm_account(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = serializer_conferma_account.loads(token, max_age=86400)
    except SignatureExpired:
        errore = quote_plus("Link di conferma scaduto. Richiedi una nuova registrazione.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except BadSignature:
        errore = quote_plus("Link di conferma non valido.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    id_utente = payload.get("id_utente")
    email = payload.get("email")
    if not id_utente or not email:
        errore = quote_plus("Token di conferma incompleto.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    risultato = await db.execute(
        select(Utente).where(
            Utente.id == int(id_utente),
            Utente.email == str(email),
        )
    )
    utente = risultato.scalar_one_or_none()
    if not utente:
        errore = quote_plus("Utente non trovato per questo link di conferma.")
        return RedirectResponse(
            url=f"/auth/login?error={errore}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not utente.attivo:
        utente.attivo = True
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Conferma account fallita per utente id=%s", id_utente)
            errore = quote_plus("Errore temporaneo durante la conferma account.")
            return RedirectResponse(
                url=f"/auth/login?error={errore}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    successo = quote_plus("Account confermato con successo. Ora puoi accedere.")
    return RedirectResponse(
        url=f"/auth/login?success={successo}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# -----------------------------------------------------------------------------
# PASSWORD RECOVERY - GET
# -----------------------------------------------------------------------------

@router.get("/password-recovery", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


# -----------------------------------------------------------------------------
# PASSWORD RECOVERY - POST
# -----------------------------------------------------------------------------

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
        "auth/forgot_password.html",
        {
            "request": request,
            "ok": "Se l'email esiste, riceverai un link di reset entro pochi minuti.",
        },
    )


# -----------------------------------------------------------------------------
# RESET PASSWORD - GET
# -----------------------------------------------------------------------------

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
            "auth/reset_password.html",
            {
                "request": request,
                "error": "Token non valido o scaduto. Richiedi un nuovo reset.",
            },
            status_code=200,
        )
    
    return templates.TemplateResponse(
        "auth/reset_password.html",
        {"request": request, "token": token},
    )


# -----------------------------------------------------------------------------
# RESET PASSWORD - POST
# -----------------------------------------------------------------------------

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
            "auth/reset_password.html",
            {
                "request": request,
                "token": token,
                "error": "Le password non coincidono",
            },
            status_code=200,
        )
    
    # TODO: Valida complessità password
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {
                "request": request,
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
            "auth/reset_password.html",
            {
                "request": request,
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

# -----------------------------------------------------------------------------
# CONFIRM PASSWORD
# -----------------------------------------------------------------------------

@router.get("/confirm-password", response_class=HTMLResponse)
async def confirm_password_page(
    request: Request,
    next: str | None = None,
    error: str | None = None,
):
    """Pagina per conferma password"""
    return templates.TemplateResponse(
        "auth/confirm_password.html",
        {
            "request": request,
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
            "auth/confirm_password.html",
            {
                "request": request,
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


# -----------------------------------------------------------------------------
# 2FA (TOTP)
# -----------------------------------------------------------------------------

@router.get("/2fa", response_class=HTMLResponse)
async def two_factor_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        "auth/two_factor.html",
        {"request": request, "next": next},
    )


@router.post("/2fa", response_class=HTMLResponse)
async def two_factor_submit(
    request: Request,
    code: str = Form(...),
    next: str = Form("/"),
):
    # TODO: validate TOTP code
    ok = (code == "123456")

    if not ok:
        return templates.TemplateResponse(
            "auth/two_factor.html",
            {"request": request, "next": next, "error": "Codice non valido"},
            status_code=200,
        )

    resp = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        "session",
        "fake-session-token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return resp
