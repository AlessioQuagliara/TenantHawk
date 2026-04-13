# =============================================================================
# backend/app/core/email.py
# =============================================================================

from __future__ import annotations

import html as html_utils
import logging
import re

from pathlib import Path

import resend

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from app.core.infrastructure.config import settings

logger = logging.getLogger(__name__)

_EMAIL_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "email"
_email_templates = Environment(
    loader=FileSystemLoader(str(_EMAIL_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _render_email_template(nome_template: str, **contesto: str) -> str:
    template = _email_templates.get_template(nome_template)
    return template.render(**contesto)


def _testo_da_html(contenuto_html: str) -> str:
    senza_stile = re.sub(r"<(script|style).*?>.*?</\1>", " ", contenuto_html, flags=re.IGNORECASE | re.DOTALL)
    senza_tag = re.sub(r"<[^>]+>", " ", senza_stile)
    decodificato = html_utils.unescape(senza_tag)
    return re.sub(r"\s+", " ", decodificato).strip()


def _invia_html_resend(
    *,
    destinatario: str,
    oggetto: str,
    html: str,
) -> None:
    if not settings.resend_api_key or settings.resend_api_key.startswith("re_chiave_"):
        logger.warning("Invio email saltato: APP_RESEND_API_KEY non configurata correttamente.")
        return

    mittente = settings.reset_email_from.strip()
    if not mittente:
        logger.warning("Invio email saltato: APP_RESET_EMAIL_FROM non configurato.")
        return

    resend.api_key = settings.resend_api_key

    def _invio_con_mittente(mittente_corrente: str) -> None:
        params: resend.Emails.SendParams = {
            "from": mittente_corrente,
            "to": [destinatario],
            "subject": oggetto,
            "html": html,
            "text": _testo_da_html(html),
        }
        resend.Emails.send(params)

    try:
        _invio_con_mittente(mittente)
    except resend.exceptions.ResendError as errore:
        messaggio_errore = str(getattr(errore, "message", errore)).lower()
        fallback = settings.resend_dev_fallback_from.strip()
        dominio_non_verificato = "domain is not verified" in messaggio_errore
        puo_usare_fallback = bool(fallback) and fallback != mittente

        if dominio_non_verificato and puo_usare_fallback:
            logger.warning(
                "Dominio mittente non verificato (%s). Riprovo con fallback dev (%s).",
                mittente,
                fallback,
            )
            _invio_con_mittente(fallback)
            return

        raise


def manda_reset_password(to_email: str, reset_link: str) -> None:
    try:
        html = _render_email_template("reset_password.html", reset_link=reset_link)
        _invia_html_resend(
            destinatario=to_email,
            oggetto="Reimposta la tua password",
            html=html,
        )
    except TemplateNotFound:
        logger.exception("Template email reset password non trovato.")
    except Exception:
        logger.exception("Errore durante invio email reset password.")


def manda_conferma_account(
    to_email: str,
    conferma_link: str,
    nome_tenant: str,
) -> None:
    try:
        html = _render_email_template(
            "confirm_account.html",
            conferma_link=conferma_link,
            nome_tenant=nome_tenant,
        )
        _invia_html_resend(
            destinatario=to_email,
            oggetto="Conferma il tuo account",
            html=html,
        )
    except TemplateNotFound:
        logger.exception("Template email conferma account non trovato.")
    except Exception:
        logger.exception("Errore durante invio email conferma account.")


def manda_invito_utente(
    to_email: str,
    conferma_link: str,
    nome_tenant: str,
    password_temporanea: str | None,
    ruolo: str,
    usa_password_attuale: bool = False,
) -> None:
    try:
        html = _render_email_template(
            "invite_user.html",
            conferma_link=conferma_link,
            nome_tenant=nome_tenant,
            password_temporanea=password_temporanea,
            ruolo=ruolo,
            usa_password_attuale=usa_password_attuale,
        )
        _invia_html_resend(
            destinatario=to_email,
            oggetto=f"Invito a {nome_tenant}",
            html=html,
        )
    except TemplateNotFound:
        logger.exception("Template email invito utente non trovato.")
    except Exception:
        logger.exception("Errore durante invio email invito utente.")


def manda_notifica_sottoscrizione(
    to_email: str,
    nome_tenant: str,
    operazione: str,
    stato: str | None = None,
    piano: str | None = None,
    dettagli: str | None = None,
) -> None:
    try:
        html = _render_email_template(
            "subscription_event.html",
            nome_tenant=nome_tenant,
            operazione=operazione,
            stato=stato or "n/d",
            piano=piano or "n/d",
            dettagli=dettagli or "",
        )
        _invia_html_resend(
            destinatario=to_email,
            oggetto=f"Aggiornamento abbonamento - {nome_tenant}",
            html=html,
        )
    except TemplateNotFound:
        logger.exception("Template email evento abbonamento non trovato.")
    except Exception:
        logger.exception("Errore durante invio email evento abbonamento.")
