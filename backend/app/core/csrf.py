# =============================================================================
# backend/app/core/csrf.py
# =============================================================================

from __future__ import annotations

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings


# Token CSRF firmati con scadenza temporale
class CSRFProtection:

    def __init__(self):
        self.serializer = URLSafeTimedSerializer(
            settings.secret_key,
            salt="csrf-token",
        )

        self.max_age = 3600 # Token valido 1h
    
    # Genera token CSRF legato a id_sessione_utente
    def genera_token(self, id_sessione_utente: str) -> str:
        return self.serializer.dumps(id_sessione_utente)

    # Verifica token CSRD e scadenza
    def valida_token(self, id_sessione_utente: str, token: str) -> bool:
        try:
            data = self.serializer.loads(token, max_age=self.max_age)
            return data == id_sessione_utente
        except (BadSignature, SignatureExpired):
            return False

csrf_protezione = CSRFProtection()
