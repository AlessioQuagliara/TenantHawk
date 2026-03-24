# =============================================================================
# backend/app/schemas/__init__.py
# =============================================================================

from .tenant import TenantBase, TenantCreazione, TenantLettura

from .utente import UtenteBase, UtenteCreazione, UtenteLettura

from .impostazioni import (
    ImpostazioniPasswordAggiornamento,
    ImpostazioniProfiloAggiornamento,
)
