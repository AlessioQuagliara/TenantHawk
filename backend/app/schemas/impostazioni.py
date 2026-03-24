# =============================================================================
# backend/app/schemas/impostazioni.py
# =============================================================================

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class ImpostazioniProfiloAggiornamento(BaseModel):
    nome: str
    email: EmailStr


class ImpostazioniPasswordAggiornamento(BaseModel):
    password_attuale: str
    password_nuova: str
    password_nuova_conferma: str
