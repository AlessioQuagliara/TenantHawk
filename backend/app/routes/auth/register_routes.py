# =============================================================================
# backend/app/routes/auth/register_routes.py
# =============================================================================

from __future__ import annotations

import logging

from urllib.parse import quote_plus

from itsdangerous import BadSignature, SignatureExpired

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Response, status

from fastapi.responses import HTMLResponse, RedirectResponse

from sqlalchemy import select

from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.billing import crea_sottoscrizione_trial_tenant

from app.core.security.csrf import csrf_protezione

from app.core.infrastructure.database import get_db

from app.core.infrastructure.email import manda_conferma_account

from app.core.security.sicurezza import hash_password, verifica_password_async

from app.models import Tenant, Utente, UtenteRuolo, UtenteRuoloTenant

from .helpers import (
    contesto_registrazione,
    costruisci_url_assoluto,
    normalizza_slug_tenant,
    serializer_conferma_account,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        contesto_registrazione(request),
    )


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

        if richiede_conferma_email:
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
