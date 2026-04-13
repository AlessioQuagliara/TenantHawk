# =============================================================================
# backend/app/core/billing.py
# =============================================================================

from __future__ import annotations

from app.core.billing.billing_models import (
    GIORNI_PROVA_DEFAULT,
    GIORNI_TREGUA_DISATTIVAZIONE,
    LIMITI_UTENTI_PER_PIANO,
    TREGUA_MARKER_MICROSECOND,
    _calcola_scadenza_tregua,
    _e_scadenza_tregua,
    _normalizza_data_utc,
    _to_int,
    datetime_da_unix,
    max_utenti_per_piano,
    piano_da_price_id,
    price_id_per_piano,
    stripe_configurato,
    stripe_live_sync_configurato,
)

from app.core.billing.billing_sync import (
    _errore_stripe_subscription_inesistente,
    _estrai_price_id_da_subscription,
    _scegli_subscription_rilevante,
    estrai_current_period_end_unix_da_subscription,
    invoice_pagata_da_subscription_obj,
    sincronizza_sottoscrizione_da_stripe,
    sincronizza_sottoscrizione_tenant_live,
    stato_interno_da_stato_stripe,
    stato_stripe_effettivo,
    trova_sottoscrizione_per_riferimenti,
)

from app.core.billing.billing_policy import (
    applica_policy_disattivazione_tenant,
    crea_sottoscrizione_trial_tenant,
    elimina_tenant_e_cascade,
)

__all__ = [
    "GIORNI_PROVA_DEFAULT",
    "GIORNI_TREGUA_DISATTIVAZIONE",
    "LIMITI_UTENTI_PER_PIANO",
    "TREGUA_MARKER_MICROSECOND",
    "_calcola_scadenza_tregua",
    "_e_scadenza_tregua",
    "_normalizza_data_utc",
    "_to_int",
    "datetime_da_unix",
    "max_utenti_per_piano",
    "piano_da_price_id",
    "price_id_per_piano",
    "stripe_configurato",
    "stripe_live_sync_configurato",
    "_errore_stripe_subscription_inesistente",
    "_estrai_price_id_da_subscription",
    "_scegli_subscription_rilevante",
    "estrai_current_period_end_unix_da_subscription",
    "invoice_pagata_da_subscription_obj",
    "sincronizza_sottoscrizione_da_stripe",
    "sincronizza_sottoscrizione_tenant_live",
    "stato_interno_da_stato_stripe",
    "stato_stripe_effettivo",
    "trova_sottoscrizione_per_riferimenti",
    "applica_policy_disattivazione_tenant",
    "crea_sottoscrizione_trial_tenant",
    "elimina_tenant_e_cascade",
]
