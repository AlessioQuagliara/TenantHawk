# =============================================================================
# backend/app/routes/auth/session_utils.py
# =============================================================================

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import Request, Response

from fastapi.responses import RedirectResponse

from app.core.security.auth import SESSION_COOKIE_NAME
from app.core.security.sessione import gestore_sessioni
from app.core.tenancy import tenant_ha_accesso
from app.models import Tenant, Utente

from .helpers import estrai_slug_tenant_da_next


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
        status_code=303,
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
