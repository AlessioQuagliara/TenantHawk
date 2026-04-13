# =============================================================================
# backend/app/routes/admin/template_context.py
# =============================================================================

from __future__ import annotations

import math

from datetime import datetime, timezone

from app.models import Sottoscrizione, SottoscrizioniStati


def _normalizza_data_utc(data: datetime | None) -> datetime | None:
    if data is None:
        return None
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def giorni_rimasti_trial_da_sottoscrizione(
    sottoscrizione: Sottoscrizione | None,
) -> int | None:
    if sottoscrizione is None:
        return None
    if sottoscrizione.stato_piano != SottoscrizioniStati.PROVA:
        return None

    fine_periodo = _normalizza_data_utc(sottoscrizione.fine_periodo_corrente)
    if fine_periodo is None:
        return None

    adesso = datetime.now(timezone.utc)
    secondi_rimanenti = (fine_periodo - adesso).total_seconds()
    if secondi_rimanenti <= 0:
        return 0

    # Ceil mantiene il comportamento UX atteso: appena parte la prova mostra 14.
    return int(math.ceil(secondi_rimanenti / 86400))
