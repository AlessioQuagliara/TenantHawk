# =============================================================================
# backend/app/models/tenant.py
# =============================================================================

from __future__ import annotations

from typing import TYPE_CHECKING, List

import enum

from sqlalchemy import String, Boolean, DateTime, func

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.utente import Utente, UtenteRuoloTenant


# -----------------------------------------------------------------------------
# ENUM RUOLI UTENTE -----------------------------------------------------------
# -----------------------------------------------------------------------------

class UtenteRuolo(str, enum.Enum):
    """
    Ruoli disponibili per utenti in un tenant.
    
    - SUPERUTENTE: Accesso completo, può gestire altri utenti
    - COLLABORATORE: Può creare/modificare contenuti
    - MODERATORE: Può moderare contenuti ma non eliminarli
    - UTENTE: Solo lettura
    """
    
    SUPERUTENTE = "superutente"
    COLLABORATORE = "collaboratore"
    MODERATORE = "moderatore"
    UTENTE = "utente"


# -----------------------------------------------------------------------------
# MODELLO TENANT --------------------------------------------------------------
# -----------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    slug: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )

    nome: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    attivo: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    creato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relazioni
    utenti: Mapped[List["Utente"]] = relationship(
        back_populates="tenant",
    )
    
    ruoli_utenti: Mapped[List["UtenteRuoloTenant"]] = relationship(
        back_populates="tenant",
    )
