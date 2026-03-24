# =============================================================================
# backend/app/models/sottoscrizione.py
# =============================================================================

from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SQLEnum

from sqlalchemy import String, DateTime, func, ForeignKey

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.tenant import Tenant


# -----------------------------------------------------------------------------
# ENUM SOTTOSCRIZIONI ---------------------------------------------------------
# -----------------------------------------------------------------------------

class Sottoscrizioni(str, Enum):
    BASE = "base"
    PRO = "pro"
    COMPANY = "company"

# -----------------------------------------------------------------------------
# ENUM STATI SOTTOSCRIZIONI ---------------------------------------------------
# -----------------------------------------------------------------------------

class SottoscrizioniStati(str, Enum):
    PROVA = "prova"
    ATTIVO = "attivo"
    SOSPESO = "sospeso"
    SCADUTO = "scaduto"
    CANCELLATO = "cancellato"

# -----------------------------------------------------------------------------
# MODELLO SOTTOSCRIZIONI ------------------------------------------------------
# -----------------------------------------------------------------------------

class Sottoscrizione(Base):
    __tablename__ = "sottoscrizione"
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"),
        nullable=False,
    )
    
    id_stripe_cliente: Mapped[str] = mapped_column(
        String(length=64),
        unique=True,
        index=True,
        nullable=True,
    )

    id_stripe_sottoscrizione: Mapped[str] = mapped_column(
        String(length=64),
        unique=True,
        index=True,
        nullable=True,
    )

    piano: Mapped[Sottoscrizioni] = mapped_column(
        SQLEnum(Sottoscrizioni),
        nullable=False,
    )

    stato_piano: Mapped[SottoscrizioniStati] = mapped_column(
        SQLEnum(SottoscrizioniStati),
        nullable=False,
    )

    fine_periodo_corrente: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    creato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    aggiornato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relazioni

    tenant: Mapped["Tenant"] = relationship(
        back_populates="sottoscrizione",
    )
