# =============================================================================
# backend/app/routes/admin/users.py
# =============================================================================

from __future__ import annotations

import secrets

from urllib.parse import urlencode

from itsdangerous import URLSafeTimedSerializer

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, status

from fastapi.responses import HTMLResponse, RedirectResponse

from pydantic import EmailStr, TypeAdapter, ValidationError

from sqlalchemy import and_, func, or_, select

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import templates

from app.core.auth import prendi_utente_corrente

from app.core.config import settings

from app.core.database import get_db

from app.core.email import manda_invito_utente

from app.core.permessi import prendi_ruolo_corrente, richiede_ruolo

from app.core.sicurezza import hash_password

from app.core.tenancy import prendi_tenant_con_accesso

from app.models import Tenant, Utente, UtenteRuolo, UtenteRuoloTenant

from app.core.billing import max_utenti_per_piano

router = APIRouter()

# -----------------------------------------------------------------------------
# SERIALIZZATORI --------------------------------------------------------------
# -----------------------------------------------------------------------------

_EMAIL_ADAPTER = TypeAdapter(EmailStr)

_SERIALIZER_CONFERMA_ACCOUNT = URLSafeTimedSerializer(
    settings.secret_key,
    salt="conferma-account",
)
_RUOLI_GESTIBILI = [
    UtenteRuolo.COLLABORATORE,
    UtenteRuolo.MODERATORE,
    UtenteRuolo.UTENTE,
]
_RUOLI_GESTIBILI_VALORI = {ruolo.value for ruolo in _RUOLI_GESTIBILI}


def _ruolo_label(ruolo: str) -> str:
    if ruolo == UtenteRuolo.SUPERUTENTE.value:
        return "Superutente"
    if ruolo == UtenteRuolo.COLLABORATORE.value:
        return "Collaboratore"
    if ruolo == UtenteRuolo.MODERATORE.value:
        return "Moderatore"
    return "Utente"


def _normalizza_ruolo(ruolo: UtenteRuolo | str | None) -> str:
    if ruolo is None:
        return UtenteRuolo.UTENTE.value
    if hasattr(ruolo, "value"):
        return str(ruolo.value)
    return str(ruolo)


def _normalizza_nome(nome: str) -> str:
    return " ".join(nome.strip().split())


def _redirect_users(
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

    base_url = f"/{tenant_slug}/admin/users"
    if not params:
        return RedirectResponse(url=base_url, status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(
        url=f"{base_url}?{urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _carica_ruolo_tenant(
    db: AsyncSession,
    *,
    id_utente: int,
    id_tenant: int,
) -> UtenteRuoloTenant | None:
    risultato = await db.execute(
        select(UtenteRuoloTenant).where(
            UtenteRuoloTenant.utente_id == id_utente,
            UtenteRuoloTenant.tenant_id == id_tenant,
        )
    )
    return risultato.scalars().first()


async def _carica_utente_tenant(
    db: AsyncSession,
    *,
    id_utente: int,
    id_tenant: int,
) -> Utente | None:
    risultato = await db.execute(
        select(Utente)
        .join(
            UtenteRuoloTenant,
            and_(
                UtenteRuoloTenant.utente_id == Utente.id,
                UtenteRuoloTenant.tenant_id == id_tenant,
            ),
        )
        .where(Utente.id == id_utente)
    )
    return risultato.scalar_one_or_none()


async def _conta_utenti_tenant(
    db: AsyncSession,
    *,
    id_tenant: int,
) -> int:
    risultato = await db.execute(
        select(func.count(func.distinct(UtenteRuoloTenant.utente_id))).where(
            UtenteRuoloTenant.tenant_id == id_tenant,
        )
    )
    totale = risultato.scalar_one()
    return int(totale or 0)


async def _calcola_limiti_invito(
    db: AsyncSession,
    *,
    tenant_obj: Tenant,
) -> tuple[int, int, bool]:
    piano = tenant_obj.sottoscrizione.piano if tenant_obj.sottoscrizione else None
    max_utenti = max_utenti_per_piano(piano) if piano else 0
    n_utenti = await _conta_utenti_tenant(db, id_tenant=tenant_obj.id)
    puo_invitare = n_utenti < max_utenti
    return max_utenti, n_utenti, puo_invitare


# -----------------------------------------------------------------------------
# ROTTE USERS -----------------------------------------------------------------
# -----------------------------------------------------------------------------


@router.get("/users", response_class=HTMLResponse)
async def users_index(
    request: Request,
    search: str = Query(""),
    filter_role: str = Query(""),
    filter_status: str = Query(""),
    ok: str | None = None,
    errore: str | None = None,
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    ruolo_corrente: str = Depends(prendi_ruolo_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    filtro_ricerca = search.strip()

    stmt = (
        select(Utente, UtenteRuoloTenant.ruolo)
        .join(
            UtenteRuoloTenant,
            and_(
                UtenteRuoloTenant.utente_id == Utente.id,
                UtenteRuoloTenant.tenant_id == tenant_obj.id,
            ),
        )
        .order_by(Utente.creato_il.desc(), Utente.id.desc())
    )

    if filtro_ricerca:
        pattern = f"%{filtro_ricerca}%"
        stmt = stmt.where(
            or_(
                Utente.email.ilike(pattern),
                Utente.nome.ilike(pattern),
            )
        )

    if filter_role in {ruolo.value for ruolo in UtenteRuolo}:
        stmt = stmt.where(UtenteRuoloTenant.ruolo == filter_role)

    if filter_status == "attivo":
        stmt = stmt.where(Utente.attivo.is_(True))
    elif filter_status == "inattivo":
        stmt = stmt.where(Utente.attivo.is_(False))

    risultato = await db.execute(stmt)
    rows: list[dict[str, str | int | bool | None]] = []
    for utente_db, ruolo_db in risultato.all():
        ruolo_val = _normalizza_ruolo(ruolo_db)
        rows.append(
            {
                "id": utente_db.id,
                "nome": utente_db.nome,
                "email": utente_db.email,
                "attivo": bool(utente_db.attivo),
                "ruolo": ruolo_val,
                "ruolo_label": _ruolo_label(ruolo_val),
                "is_superutente": ruolo_val == UtenteRuolo.SUPERUTENTE.value,
                "is_self": utente_db.id == utente_corrente.id,
            }
        )

    max_utenti, n_utenti, puo_invitare = await _calcola_limiti_invito(
        db,
        tenant_obj=tenant_obj,
    )

    return templates.TemplateResponse(
        request,
        "admin/users/index.html",
        {
            "tenant": tenant_obj,
            "utente": utente_corrente,
            "ruolo_corrente": ruolo_corrente,
            "users": rows,
            "ruoli_disponibili": [ruolo.value for ruolo in _RUOLI_GESTIBILI],
            "search_value": search,
            "filter_role": filter_role,
            "filter_status": filter_status,
            "ok": ok,
            "errore": errore,
            "max_utenti": max_utenti,
            "n_utenti": n_utenti,
            "puo_invitare": puo_invitare,
        },
    )


@router.post("/users/invite")
async def users_invite(
    background_tasks: BackgroundTasks,
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    email: str = Form(...),
    nome: str = Form(""),
    ruolo: str = Form(UtenteRuolo.UTENTE.value),
    db: AsyncSession = Depends(get_db),
):
    ruolo_normalizzato = ruolo.strip().lower()
    if ruolo_normalizzato not in _RUOLI_GESTIBILI_VALORI:
        return _redirect_users(
            tenant_obj.slug,
            errore="Ruolo non valido. Seleziona collaboratore, moderatore o utente.",
        )

    email_normalizzata = email.strip().lower()
    try:
        email_validata = str(_EMAIL_ADAPTER.validate_python(email_normalizzata))
    except ValidationError:
        return _redirect_users(
            tenant_obj.slug,
            errore="Inserisci un indirizzo email valido.",
        )

    nome_normalizzato = _normalizza_nome(nome)
    if nome_normalizzato and len(nome_normalizzato) > 255:
        return _redirect_users(
            tenant_obj.slug,
            errore="Il nome supera la lunghezza massima consentita.",
        )

    max_utenti, n_utenti, puo_invitare = await _calcola_limiti_invito(
        db,
        tenant_obj=tenant_obj,
    )

    risultato = await db.execute(select(Utente).where(Utente.email == email_validata))
    utente_destinatario = risultato.scalar_one_or_none()
    ruolo_tenant: UtenteRuoloTenant | None = None
    if utente_destinatario is not None:
        ruolo_tenant = await _carica_ruolo_tenant(
            db,
            id_utente=utente_destinatario.id,
            id_tenant=tenant_obj.id,
        )

    richiede_nuovo_slot = utente_destinatario is None or ruolo_tenant is None
    if richiede_nuovo_slot and not puo_invitare:
        return _redirect_users(
            tenant_obj.slug,
            errore=(
                "Limite utenti raggiunto "
                f"({n_utenti}/{max_utenti}) per il piano corrente."
            ),
        )

    password_temporanea: str | None = None
    usa_password_attuale = False

    if utente_destinatario is None:
        password_temporanea = secrets.token_urlsafe(12)
        utente_destinatario = Utente(
            tenant_id=tenant_obj.id,
            nome=nome_normalizzato or None,
            email=email_validata,
            hashed_password=hash_password(password_temporanea),
            attivo=False,
        )
        db.add(utente_destinatario)
        await db.flush()
    else:
        if utente_destinatario.id == utente_corrente.id:
            return _redirect_users(
                tenant_obj.slug,
                errore="Non puoi invitare nuovamente il tuo account.",
            )

        if nome_normalizzato and not (utente_destinatario.nome or "").strip():
            utente_destinatario.nome = nome_normalizzato

        if not utente_destinatario.attivo:
            password_temporanea = secrets.token_urlsafe(12)
            utente_destinatario.hashed_password = hash_password(password_temporanea)
        else:
            usa_password_attuale = True

    if ruolo_tenant is None:
        ruolo_tenant = UtenteRuoloTenant(
            utente_id=utente_destinatario.id,
            tenant_id=tenant_obj.id,
            ruolo=ruolo_normalizzato,
        )
        db.add(ruolo_tenant)
    else:
        if _normalizza_ruolo(ruolo_tenant.ruolo) == UtenteRuolo.SUPERUTENTE.value:
            return _redirect_users(
                tenant_obj.slug,
                errore="Non puoi convertire o reinvitare un superutente da questa pagina.",
            )
        ruolo_tenant.ruolo = ruolo_normalizzato

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _redirect_users(
            tenant_obj.slug,
            errore="Email già presente, impossibile completare l'invito.",
        )
    except SQLAlchemyError:
        await db.rollback()
        return _redirect_users(
            tenant_obj.slug,
            errore="Errore temporaneo durante la creazione dell'invito.",
        )

    token_conferma = _SERIALIZER_CONFERMA_ACCOUNT.dumps(
        {
            "id_utente": utente_destinatario.id,
            "email": utente_destinatario.email,
        }
    )
    link_conferma = (
        f"{settings.app_base_url.rstrip('/')}/auth/confirm-account?token={token_conferma}"
    )
    background_tasks.add_task(
        manda_invito_utente,
        utente_destinatario.email,
        link_conferma,
        tenant_obj.nome,
        password_temporanea,
        _ruolo_label(ruolo_normalizzato),
        usa_password_attuale,
    )

    messaggio_ok = "Invito inviato via email con token di conferma."
    if password_temporanea:
        messaggio_ok = (
            "Invito inviato via email con token di conferma e password temporanea."
        )
    elif usa_password_attuale:
        messaggio_ok = (
            "Invito inviato via email. L'utente può accedere con la password attuale."
        )

    return _redirect_users(
        tenant_obj.slug,
        ok=messaggio_ok,
    )


@router.post("/users/{user_id}/role")
async def users_change_role(
    user_id: int,
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    ruolo: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ruolo_normalizzato = ruolo.strip().lower()
    if ruolo_normalizzato not in _RUOLI_GESTIBILI_VALORI:
        return _redirect_users(
            tenant_obj.slug,
            errore="Ruolo non valido per questa operazione.",
        )

    utente_target = await _carica_utente_tenant(
        db,
        id_utente=user_id,
        id_tenant=tenant_obj.id,
    )
    if utente_target is None:
        return _redirect_users(
            tenant_obj.slug,
            errore="Utente non trovato.",
        )
    if utente_target.id == utente_corrente.id:
        return _redirect_users(
            tenant_obj.slug,
            errore="Non puoi modificare il tuo ruolo da questa pagina.",
        )

    ruolo_tenant = await _carica_ruolo_tenant(
        db,
        id_utente=utente_target.id,
        id_tenant=tenant_obj.id,
    )
    ruolo_corrente_target = _normalizza_ruolo(ruolo_tenant.ruolo if ruolo_tenant else None)
    if ruolo_corrente_target == UtenteRuolo.SUPERUTENTE.value:
        return _redirect_users(
            tenant_obj.slug,
            errore="Non puoi modificare il ruolo di un superutente.",
        )

    if ruolo_tenant is None:
        ruolo_tenant = UtenteRuoloTenant(
            utente_id=utente_target.id,
            tenant_id=tenant_obj.id,
            ruolo=ruolo_normalizzato,
        )
        db.add(ruolo_tenant)
    else:
        ruolo_tenant.ruolo = ruolo_normalizzato

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        return _redirect_users(
            tenant_obj.slug,
            errore="Errore durante l'aggiornamento del ruolo.",
        )

    return _redirect_users(
        tenant_obj.slug,
        ok="Ruolo aggiornato con successo.",
    )


@router.post("/users/{user_id}/toggle-ban")
async def users_toggle_ban(
    user_id: int,
    tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
    db: AsyncSession = Depends(get_db),
):
    utente_target = await _carica_utente_tenant(
        db,
        id_utente=user_id,
        id_tenant=tenant_obj.id,
    )
    if utente_target is None:
        return _redirect_users(
            tenant_obj.slug,
            errore="Utente non trovato.",
        )
    if utente_target.id == utente_corrente.id:
        return _redirect_users(
            tenant_obj.slug,
            errore="Non puoi bannare il tuo account.",
        )

    ruolo_tenant = await _carica_ruolo_tenant(
        db,
        id_utente=utente_target.id,
        id_tenant=tenant_obj.id,
    )
    if _normalizza_ruolo(ruolo_tenant.ruolo if ruolo_tenant else None) == UtenteRuolo.SUPERUTENTE.value:
        return _redirect_users(
            tenant_obj.slug,
            errore="Non puoi bannare un superutente.",
        )

    utente_target.attivo = not bool(utente_target.attivo)

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        return _redirect_users(
            tenant_obj.slug,
            errore="Errore durante l'aggiornamento dello stato utente.",
        )

    if utente_target.attivo:
        return _redirect_users(
            tenant_obj.slug,
            ok="Utente riattivato con successo.",
        )
    return _redirect_users(
        tenant_obj.slug,
        ok="Utente bannato con successo.",
    )
