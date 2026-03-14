# =============================================================================
# backend/app/models/__init__.py
# =============================================================================

from .tenant import Tenant, UtenteRuolo # noqa: F401

from .utente import Utente, UtenteRuoloTenant, TokenResetPassword # noqa: F401

__all__ = [
    "Base",
    "Tenant",
    "Utente",
    "TokenResetPassword",
    "UtenteRuoloTenant",
    "UtenteRuolo",
]