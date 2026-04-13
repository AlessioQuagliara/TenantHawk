# =============================================================================
# backend/app/models/utente.py
# =============================================================================

from __future__ import annotations

from typing import TYPE_CHECKING, List

from sqlalchemy import String, Boolean, ForeignKey, DateTime

from sqlalchemy.sql import func

from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import Enum as SQLEnum

from app.core.infrastructure.database import Base

from app.models.tenant import UtenteRuolo

if TYPE_CHECKING:
    from app.models.tenant import Tenant


# -----------------------------------------------------------------------------
# MODELLO UTENTE --------------------------------------------------------------
# -----------------------------------------------------------------------------

class Utente(Base):
    __tablename__ = "utente"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    nome: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    attivo: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"),
        nullable=False,
        index=True,
    )

    creato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relazioni
    tenant: Mapped["Tenant"] = relationship(
        back_populates="utenti",
    )

    token_reset: Mapped[List["TokenResetPassword"]] = relationship(
        back_populates="utente",
    )
    
    ruoli: Mapped[List["UtenteRuoloTenant"]] = relationship(
        back_populates="utente",
    )


# -----------------------------------------------------------------------------
# MODELLO TOKEN RESET PASSWORD ------------------------------------------------
# -----------------------------------------------------------------------------

class TokenResetPassword(Base):
    """Token temporaneo per reset password (valido 1 ora)"""
    __tablename__ = "token_reset_password"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    utente_id: Mapped[int] = mapped_column(
        ForeignKey("utente.id"),
        nullable=False,
    )

    token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )

    creato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scade_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    usato: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Relazione
    utente: Mapped["Utente"] = relationship(
        back_populates="token_reset",
    )


# -----------------------------------------------------------------------------
# MODELLO RUOLI UTENTE-TENANT (Many-to-Many) ---------------------------------
# -----------------------------------------------------------------------------

class UtenteRuoloTenant(Base):
    """
    Tabella associativa per ruoli utente per-tenant.
    
    Un utente può avere ruoli diversi in tenant diversi:
    - Utente X è SUPERUTENTE in Tenant A
    - Utente X è UTENTE in Tenant B
    """
    __tablename__ = "utente_ruolo_tenant"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    utente_id: Mapped[int] = mapped_column(
        ForeignKey("utente.id"),
        nullable=False,
        index=True,
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"),
        nullable=False,
        index=True,
    )

    ruolo: Mapped[str] = mapped_column(
        SQLEnum(UtenteRuolo, name="utente_ruolo_enum", native_enum=False),
        nullable=False,
        default=UtenteRuolo.UTENTE,
    )

    assegnato_il: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relazioni
    utente: Mapped["Utente"] = relationship(
        back_populates="ruoli",
    )

    tenant: Mapped["Tenant"] = relationship(
        back_populates="ruoli_utenti",
    )
