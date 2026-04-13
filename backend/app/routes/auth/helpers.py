# =============================================================================
# backend/app/routes/auth/helpers.py
# =============================================================================

from __future__ import annotations

import re
import secrets

from unicodedata import normalize

from itsdangerous import URLSafeTimedSerializer

from fastapi import Request

from app.core.infrastructure.config import settings
from app.core.security.csrf import csrf_protezione
from app.models import Tenant

serializer_conferma_account = URLSafeTimedSerializer(
    settings.secret_key,
    salt="conferma-account",
)
serializer_selezione_tenant_login = URLSafeTimedSerializer(
    settings.secret_key,
    salt="selezione-tenant-login",
)
SELEZIONE_TENANT_MAX_AGE_SECONDI = 600


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
