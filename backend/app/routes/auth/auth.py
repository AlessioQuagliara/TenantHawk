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

from sqlalchemy import and_, select

from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

from sqlalchemy.orm import joinedload, selectinload

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.database import get_db

from app.core.sicurezza import verifica_password_async, hash_password

from app.core.sessione import gestore_sessioni

from app.core.config import settings

from app.core.csrf import csrf_protezione

from app.core.auth import SESSION_COOKIE_NAME, prendi_utente_corrente

from app.core.billing import (
    applica_policy_disattivazione_tenant,
    crea_sottoscrizione_trial_tenant,
)

from app.core.tenancy import tenant_ha_accesso

from app.models import Utente, Tenant, UtenteRuoloTenant, UtenteRuolo

from app.core.email import manda_conferma_account, manda_reset_password

logger = logging.getLogger(__name__)

router = APIRouter()

serializer_conferma_account = URLSafeTimedSerializer(
    settings.secret_key,
    salt="conferma-account",
)
serializer_selezione_tenant_login = URLSafeTimedSerializer(
    settings.secret_key,
    salt="selezione-tenant-login",
)
SELEZIONE_TENANT_MAX_AGE_SECONDI = 600

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
    _request: Request,
    *,
    nome_tenant: str = "",
    slug_tenant: str = "",
    nome_utente: str = "",
    email: str = "",
    errore: str | None = None,
) -> dict[str, str | None]:
    sessione_temporanea, token_csrf = nuovo_csrf_form()
    return {
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


def estrai_slug_tenant_da_next(next_path: str | None) -> str | None:
    if not next_path:
        return None
    match = re.match(r"^/([^/]+)/admin(?:/|$)", next_path.strip())
    if not match:
        return None
    return match.group(1)


def contesto_login(
    *,
    next_path: str = "/",
    errore: str | None = None,
    success: str | None = None,
) -> dict[str, str | None]:
    sessione_temporanea, token_csrf = nuovo_csrf_form()
    return {
        "next": next_path or "/",
        "error": errore,
        "success": success,
        "csrf_token": token_csrf,
        "sessione_temp": sessione_temporanea,
    }


async def carica_tenant_accessibili_utente(
    db: AsyncSession,
    id_utente: int,
) -> list[Tenant]:
    risultato_tenant = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.sottoscrizione))
        .join(
            UtenteRuoloTenant,
            and_(
                UtenteRuoloTenant.tenant_id == Tenant.id,
                UtenteRuoloTenant.utente_id == id_utente,
            ),
        )
        .where(Tenant.attivo.is_(True))
        .order_by(Tenant.nome.asc(), Tenant.id.asc())
    )
    tenant_risultati: list[Tenant] = []
    for tenant_item in risultato_tenant.scalars().all():
        tenant_eliminato = await applica_policy_disattivazione_tenant(
            db,
            tenant_obj=tenant_item,
        )
        if tenant_eliminato:
            continue
        # Include anche tenant sospesi/scaduti: l'utente deve poter accedere
        # all'area sottoscrizioni per riattivare il piano.
        tenant_risultati.append(tenant_item)
    return tenant_risultati


def contesto_selezione_tenant(
    *,
    token_selezione: str,
    tenant_candidati: list[Tenant],
    tenant_selezionato_slug: str | None,
    email_utente: str,
    next_path: str,
    errore: str | None = None,
) -> dict[str, object]:
    sessione_temporanea, token_csrf = nuovo_csrf_form()
    opzioni_tenant = [
        {"slug": tenant.slug, "nome": tenant.nome}
        for tenant in tenant_candidati
    ]
    slug_disponibili = {str(item["slug"]) for item in opzioni_tenant}
    if not tenant_selezionato_slug or tenant_selezionato_slug not in slug_disponibili:
        tenant_selezionato_slug = str(opzioni_tenant[0]["slug"])

    return {
        "error": errore,
        "csrf_token": token_csrf,
        "sessione_temp": sessione_temporanea,
        "token_selezione": token_selezione,
        "tenant_options": opzioni_tenant,
        "tenant_selected_slug": tenant_selezionato_slug,
        "email": email_utente,
        "next": next_path or "/",
    }


async def chiudi_sessione_corrente_browser(request: Request) -> None:
    id_sessione_corrente = request.cookies.get(SESSION_COOKIE_NAME)
    if id_sessione_corrente:
        await gestore_sessioni.cancella_sessione(id_sessione_corrente)


def costruisci_redirect_post_login(tenant: Tenant, next_path: str) -> str:
    if tenant_ha_accesso(tenant):
        redirect_url = f"/{tenant.slug}/admin/dashboard"
    else:
        messaggio = quote_plus(
            "Piano non attivo: completa o aggiorna l'abbonamento per ripristinare l'accesso."
        )
        redirect_url = f"/{tenant.slug}/admin/sottoscrizioni?errore={messaggio}"

    if next_path and next_path != "/" and next_path.startswith("/"):
        slug_tenant_next = estrai_slug_tenant_da_next(next_path)
        if slug_tenant_next is None or slug_tenant_next == tenant.slug:
            if tenant_ha_accesso(tenant):
                redirect_url = next_path
            elif next_path.startswith(f"/{tenant.slug}/admin/sottoscrizioni"):
                redirect_url = next_path
    return redirect_url


async def crea_risposta_login_ok(
    request: Request,
    *,
    utente: Utente,
    tenant: Tenant,
    next_path: str,
) -> Response | RedirectResponse:
    await chiudi_sessione_corrente_browser(request)

    id_sessione_utente = await gestore_sessioni.crea_sessione(
        id_utente=utente.id,
        id_tenant=tenant.id,
        email=utente.email,
    )

    redirect_url = costruisci_redirect_post_login(tenant, next_path)

    if request.headers.get("HX-Request") == "true":
        risposta = Response(status_code=204)
        risposta.set_cookie(
            SESSION_COOKIE_NAME,
            id_sessione_utente,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=86400,
        )
        risposta.headers["HX-Redirect"] = redirect_url
        return risposta

    risposta = RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    risposta.set_cookie(
        SESSION_COOKIE_NAME,
        id_sessione_utente,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=86400,
    )
    return risposta

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
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        contesto_login(
            next_path=next or "/",
            errore=error,
            success=success,
        ),
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
    next_path: str = Form("/", alias="next"),
    db: AsyncSession = Depends(get_db),
):
    """Login con CSRF e sessione Redis"""
    
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
                Utente.email == email,
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
        logger.exception("Login fallito: schema DB non pronto (email=%s)", email)
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
        logger.exception("Login fallito: errore database inatteso (email=%s)", email)
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


# -----------------------------------------------------------------------------
# LOGOUT
# -----------------------------------------------------------------------------

@router.post("/logout")
async def logout_submit(
    request: Request,
    utente: Utente = Depends(prendi_utente_corrente),
):
    """Logout con cancellazione sessione Redis"""
    id_sessione_utente = request.cookies.get(SESSION_COOKIE_NAME)
    
    if id_sessione_utente:
        await gestore_sessioni.cancella_sessione(id_sessione_utente)
    
    risposta = RedirectResponse(
        url="/auth/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    risposta.delete_cookie(SESSION_COOKIE_NAME)
    
    return risposta


# -----------------------------------------------------------------------------
# SIGN-UP (registrazione) - GET
# -----------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request,
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
            request,
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
            request,
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
            request,
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
            request,
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
            request,
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
            request,
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

    richiede_conferma_email = True
    invia_email_conferma = True

    try:
        risultato_tenant = await db.execute(
            select(Tenant).where(Tenant.slug == slug_tenant_finale)
        )
        tenant_esistente = risultato_tenant.scalar_one_or_none()
        if tenant_esistente:
            return templates.TemplateResponse(
                request,
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
        utente_owner: Utente
        # Supporto multi-tenant: se la email esiste, riusa lo stesso account
        # (solo dopo verifica password) e collega il nuovo tenant.
        if utente_esistente is None:
            richiede_conferma_email = True
        else:
            password_valida = await verifica_password_async(
                password,
                utente_esistente.hashed_password,
            )
            if not password_valida:
                return templates.TemplateResponse(
                    request,
                    "auth/register.html",
                    contesto_registrazione(
                        request,
                        nome_tenant=nome_tenant,
                        slug_tenant=slug_tenant_finale,
                        nome_utente=nome_utente,
                        email=email,
                        errore=(
                            "Questa email esiste già. "
                            "Per creare un nuovo tenant inserisci la password corretta dell'account."
                        ),
                    ),
                    status_code=200,
                )

            if nome_utente and not (utente_esistente.nome or "").strip():
                utente_esistente.nome = nome_utente

            utente_owner = utente_esistente
            richiede_conferma_email = not bool(utente_esistente.attivo)

        nuovo_tenant = Tenant(
            slug=slug_tenant_finale,
            nome=nome_tenant,
            attivo=True,
        )
        db.add(nuovo_tenant)
        await db.flush()
        await crea_sottoscrizione_trial_tenant(
            db,
            tenant_id=nuovo_tenant.id,
        )

        if utente_esistente is None:
            utente_owner = Utente(
                tenant_id=nuovo_tenant.id,
                nome=nome_utente or None,
                email=email,
                hashed_password=hash_password(password),
                attivo=False,
            )
            db.add(utente_owner)
            await db.flush()

        ruolo_tenant = UtenteRuoloTenant(
            utente_id=utente_owner.id,
            tenant_id=nuovo_tenant.id,
            # Chi si registra creando il tenant è il proprietario iniziale.
            ruolo=UtenteRuolo.SUPERUTENTE,
        )
        db.add(ruolo_tenant)
        await db.commit()

        if invia_email_conferma:
            token_conferma = serializer_conferma_account.dumps(
                {"id_utente": utente_owner.id, "email": utente_owner.email}
            )
            link_conferma = costruisci_url_assoluto(
                f"/auth/confirm-account?token={token_conferma}"
            )
            background_tasks.add_task(
                manda_conferma_account,
                utente_owner.email,
                link_conferma,
                nome_tenant,
            )
    except ProgrammingError:
        await db.rollback()
        logger.exception("Registrazione fallita: schema DB non pronto (email=%s)", email)
        return templates.TemplateResponse(
            request,
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
            request,
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
            request,
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

    if richiede_conferma_email:
        messaggio_successo = quote_plus(
            "Registrazione completata. Controlla la tua email per confermare l'account."
        )
        url_redirect = f"/auth/login?success={messaggio_successo}"
    else:
        messaggio_successo = quote_plus(
            "Tenant creato con successo. Accedi per entrare nel nuovo tenant."
        )
        next_path = quote_plus(f"/{slug_tenant_finale}/admin/dashboard")
        url_redirect = f"/auth/login?success={messaggio_successo}&next={next_path}"

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
    return templates.TemplateResponse(
        request,
        "auth/forgot_password.html",
        {},
    )


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
        request,
        "auth/forgot_password.html",
        {
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


# -----------------------------------------------------------------------------
# 2FA (TOTP)
# -----------------------------------------------------------------------------

@router.get("/2fa", response_class=HTMLResponse)
async def two_factor_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        request,
        "auth/two_factor.html",
        {"next": next},
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
            request,
            "auth/two_factor.html",
            {"next": next, "error": "Codice non valido"},
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
