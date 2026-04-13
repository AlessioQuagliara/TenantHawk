# =============================================================================
# backend/app/core/gestione_errori.py
# =============================================================================

from __future__ import annotations

import logging

import re

from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Request

from fastapi.responses import HTMLResponse, JSONResponse

from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.infrastructure.config import settings
from app.core.infrastructure.templates import templates

logger = logging.getLogger(__name__)

# Path admin valido:
# - /{tenant}/admin
# - /{tenant}/admin/...
REGEX_PATH_ADMIN = re.compile(r"^/[^/]+/admin(?:/.*)?$")
CODICI_TEMPLATE_GESTITI = {401, 403, 404, 500}

TESTI_ERRORE: dict[int, dict[str, str]] = {
    401: {
        "titolo": "Accesso non autorizzato",
        "messaggio": "Devi autenticarti per accedere a questa risorsa.",
        "messaggio_admin": "Sessione admin mancante o scaduta. Effettua nuovamente il login.",
    },
    403: {
        "titolo": "Accesso vietato",
        "messaggio": "Non hai i permessi necessari per visualizzare questa pagina.",
        "messaggio_admin": "Permessi insufficienti per questa sezione dell'area admin.",
    },
    404: {
        "titolo": "Pagina non trovata",
        "messaggio": "La risorsa richiesta non esiste o non è più disponibile.",
        "messaggio_admin": "La pagina admin richiesta non esiste o non è raggiungibile.",
    },
    500: {
        "titolo": "Errore interno",
        "messaggio": "Si è verificato un errore interno. Riprova tra poco.",
        "messaggio_admin": "Errore interno nell'area admin. Controlla i log applicativi.",
    },
}


def richiesta_html(richiesta: Request) -> bool:
    """
    Riconosce richieste orientate al rendering HTML.

    Include anche HTMX, che richiede frammenti/template HTML.
    """
    if richiesta.headers.get("HX-Request", "").lower() == "true":
        return True

    header_accept = richiesta.headers.get("accept", "").lower()
    return "text/html" in header_accept


def percorso_admin(path: str) -> bool:
    """True quando il path rispetta /{tenant}/admin o /{tenant}/admin/..."""
    return bool(REGEX_PATH_ADMIN.match(path))


def estrai_slug_tenant(path: str) -> str | None:
    """
    Estrae lo slug tenant da path admin nel formato /{tenant}/admin/...
    """
    segmenti = [segmento for segmento in path.split("/") if segmento]
    if len(segmenti) >= 2 and segmenti[1] == "admin":
        return segmenti[0]
    return None


def percorso_completo(richiesta: Request) -> str:
    """Costruisce path + query string per eventuali redirect post-login."""
    path = richiesta.url.path
    if richiesta.url.query:
        return f"{path}?{richiesta.url.query}"
    return path


def template_errore(codice_stato: int, area_admin: bool) -> str:
    codice_template = codice_stato if codice_stato in CODICI_TEMPLATE_GESTITI else 500
    prefisso = "admin/errori" if area_admin else "errori"
    return f"{prefisso}/{codice_template}.html"


def dati_errore(codice_stato: int, area_admin: bool) -> dict[str, str]:
    codice_risolto = codice_stato if codice_stato in TESTI_ERRORE else 500
    testi = TESTI_ERRORE[codice_risolto]
    messaggio = testi["messaggio_admin"] if area_admin else testi["messaggio"]
    return {
        "titolo": testi["titolo"],
        "messaggio": messaggio,
    }


def dettaglio_http_come_stringa(eccezione: HTTPException | StarletteHTTPException) -> str:
    if isinstance(eccezione.detail, str):
        return eccezione.detail
    if eccezione.detail is None:
        return ""
    return str(eccezione.detail)


def messaggio_template_http(
    codice_stato: int,
    area_admin: bool,
    dettaglio_http: str,
) -> str:
    """
    Usa il dettaglio personalizzato solo quando è davvero utile.
    I dettagli di default Starlette (es. "Not Found") vengono sostituiti
    con testi italiani più chiari.
    """
    dettagli_default = {"not found", "unauthorized", "forbidden"}
    if dettaglio_http and dettaglio_http.lower().strip() not in dettagli_default:
        return dettaglio_http

    return dati_errore(codice_stato, area_admin)["messaggio"]


def contesto_base_template(richiesta: Request, area_admin: bool) -> dict[str, str | bool | dict[str, str] | None]:
    """
    Crea variabili condivise da tutti i template errore.
    """
    path_completo = percorso_completo(richiesta)
    slug_tenant = estrai_slug_tenant(richiesta.url.path)
    url_home_pubblica = settings.app_base_url.rstrip("/")
    url_dashboard_admin = (
        f"/{slug_tenant}/auth/login"
        if slug_tenant
        else url_home_pubblica
    )

    return {
        "area_admin": area_admin,
        "percorso_richiesto": path_completo,
        "url_login": f"/auth/login?next={quote_plus(path_completo)}",
        "url_home_pubblica": url_home_pubblica,
        "url_dashboard_admin": url_dashboard_admin,
        # Variabili di fallback per template che includono elementi admin condivisi.
        "tenant": {"slug": slug_tenant or ""},
        "utente": {"nome": "Utente"},
        "ruolo_corrente": None,
    }


def risposta_html_fallback(
    codice_stato: int,
    titolo: str,
    messaggio: str,
) -> HTMLResponse:
    html = f"""
    <!doctype html>
    <html lang="it">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{codice_stato} - {titolo}</title>
      </head>
      <body style="font-family: sans-serif; padding: 2rem;">
        <h1>{codice_stato} - {titolo}</h1>
        <p>{messaggio}</p>
      </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=codice_stato)


def registra_handler_globali(app: FastAPI) -> None:
    """
    Registra i gestori globali in un punto centralizzato.
    """

    @app.exception_handler(StarletteHTTPException)
    @app.exception_handler(HTTPException)
    async def handler_http_exception(
        richiesta: Request,
        eccezione: HTTPException | StarletteHTTPException,
    ):
        codice_stato = eccezione.status_code
        area_admin = percorso_admin(richiesta.url.path)
        dettagli = dettaglio_http_come_stringa(eccezione)

        if richiesta_html(richiesta):
            dati = dati_errore(codice_stato, area_admin)
            contesto: dict[str, str | int | bool | dict[str, str] | None] = {
                "codice_errore": codice_stato,
                "titolo_errore": dati["titolo"],
                "messaggio_errore": messaggio_template_http(
                    codice_stato,
                    area_admin,
                    dettagli,
                ),
            }
            contesto.update(contesto_base_template(richiesta, area_admin))
            try:
                return templates.TemplateResponse(
                    richiesta,
                    template_errore(codice_stato, area_admin),
                    contesto,
                    status_code=codice_stato,
                )
            except Exception:
                logger.exception(
                    "Errore rendering template HTTP. codice=%s path=%s",
                    codice_stato,
                    richiesta.url.path,
                )
                return risposta_html_fallback(
                    codice_stato,
                    dati["titolo"],
                    contesto["messaggio_errore"],
                )

        return JSONResponse(
            status_code=codice_stato,
            content={
                "errore": "errore_http",
                "codice": codice_stato,
                "dettaglio": dettagli or "Errore HTTP",
                "path": richiesta.url.path,
            },
        )

    @app.exception_handler(Exception)
    async def handler_eccezione_generica(richiesta: Request, eccezione: Exception):
        area_admin = percorso_admin(richiesta.url.path)
        logger.exception(
            "Errore inatteso. path=%s metodo=%s",
            richiesta.url.path,
            richiesta.method,
            exc_info=eccezione,
        )

        if richiesta_html(richiesta):
            dati = dati_errore(500, area_admin)
            contesto: dict[str, str | int | bool | dict[str, str] | None] = {
                "codice_errore": 500,
                "titolo_errore": dati["titolo"],
                "messaggio_errore": dati["messaggio"],
            }
            contesto.update(contesto_base_template(richiesta, area_admin))
            try:
                return templates.TemplateResponse(
                    richiesta,
                    template_errore(500, area_admin),
                    contesto,
                    status_code=500,
                )
            except Exception:
                logger.exception(
                    "Errore rendering template 500. path=%s",
                    richiesta.url.path,
                )
                return risposta_html_fallback(
                    500,
                    dati["titolo"],
                    dati["messaggio"],
                )

        return JSONResponse(
            status_code=500,
            content={
                "errore": "errore_interno",
                "codice": 500,
                "dettaglio": "Errore interno del server",
                "path": richiesta.url.path,
            },
        )
