# =============================================================================
# backend/app/core/billing_models.py
# =============================================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from typing import Any

from app.core.infrastructure.config import settings

from app.models import Sottoscrizioni

# -----------------------------------------------------------------------------
# LIMITI PER PIANO ------------------------------------------------------------
# -----------------------------------------------------------------------------

GIORNI_PROVA_DEFAULT = 14
GIORNI_TREGUA_DISATTIVAZIONE = 14
TREGUA_MARKER_MICROSECOND = 987654

LIMITI_UTENTI_PER_PIANO = {
    Sottoscrizioni.BASE: 3,
    Sottoscrizioni.PRO: 10,
    Sottoscrizioni.COMPANY: 30,
}


# -----------------------------------------------------------------------------
# HELPER PURI -----------------------------------------------------------------
# -----------------------------------------------------------------------------

def max_utenti_per_piano(piano: Sottoscrizioni) -> int:
    return LIMITI_UTENTI_PER_PIANO.get(piano, 1)


def stripe_configurato() -> bool:
    return bool(
        settings.stripe_secret_key
        and settings.stripe_price_base
        and settings.stripe_price_pro
        and settings.stripe_price_company
    )


def stripe_live_sync_configurato() -> bool:
    return bool(settings.stripe_secret_key)


def price_id_per_piano(piano: Sottoscrizioni) -> str | None:
    mapping = {
        Sottoscrizioni.BASE: settings.stripe_price_base,
        Sottoscrizioni.PRO: settings.stripe_price_pro,
        Sottoscrizioni.COMPANY: settings.stripe_price_company,
    }
    price_id = mapping.get(piano)
    return str(price_id) if price_id else None


def piano_da_price_id(price_id: str | None) -> Sottoscrizioni | None:
    if not price_id:
        return None
    mapping = {
        settings.stripe_price_base: Sottoscrizioni.BASE,
        settings.stripe_price_pro: Sottoscrizioni.PRO,
        settings.stripe_price_company: Sottoscrizioni.COMPANY,
    }
    return mapping.get(price_id)


def datetime_da_unix(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalizza_data_utc(data: datetime | None) -> datetime | None:
    if data is None:
        return None
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def _calcola_scadenza_tregua(base: datetime | None = None) -> datetime:
    base_utc = _normalizza_data_utc(base) or datetime.now(timezone.utc)
    deadline = base_utc + timedelta(days=GIORNI_TREGUA_DISATTIVAZIONE)
    return deadline.replace(microsecond=TREGUA_MARKER_MICROSECOND)


def _e_scadenza_tregua(data: datetime | None) -> bool:
    data_utc = _normalizza_data_utc(data)
    if data_utc is None:
        return False
    return data_utc.microsecond == TREGUA_MARKER_MICROSECOND
