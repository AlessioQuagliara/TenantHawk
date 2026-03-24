# =============================================================================
# backend/app/core/tenancy.py
# =============================================================================

from __future__ import annotations

from datetime import datetime, timezone

from typing import Annotated

from fastapi import Depends, HTTPException, Path, status

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.core.auth import prendi_utente_corrente

from app.core.billing import applica_policy_disattivazione_tenant

from app.core.database import get_db

from app.models import SottoscrizioniStati, Tenant, Utente, UtenteRuoloTenant


def _normalizza_data_utc(data: datetime | None) -> datetime | None:   
    if data is None:
        return None
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def tenant_ha_accesso(
    tenant: Tenant,
    *,
    adesso: datetime | None = None,
) -> bool:
    """
    Verifica se il tenant puo' accedere alle aree protette.

    Regole:
    - sottoscrizione assente -> NO
    - stati consentiti: PROVA e ATTIVO
    - se `fine_periodo_corrente` e' valorizzata deve essere nel futuro
    - `PROVA` senza scadenza -> NO (configurazione incompleta)
    """
    sottoscrizione = tenant.sottoscrizione
    if sottoscrizione is None:
        return False

    stato = sottoscrizione.stato_piano
    if stato not in {SottoscrizioniStati.PROVA, SottoscrizioniStati.ATTIVO}:
        return False

    fine_periodo = sottoscrizione.fine_periodo_corrente
    if fine_periodo is None:
        return stato == SottoscrizioniStati.ATTIVO

    adesso_utc = _normalizza_data_utc(adesso) or datetime.now(timezone.utc)
    fine_periodo_utc = _normalizza_data_utc(fine_periodo) or datetime.now(timezone.utc)
    return fine_periodo_utc > adesso_utc


async def prendi_tenant_corrente(
    tenant: Annotated[str, Path(..., description="Slug del tenant")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    result = await db.execute(
        select(Tenant)
        .options(
            selectinload(Tenant.ruoli_utenti),
            selectinload(Tenant.sottoscrizione),
        )
        .where(
            Tenant.slug == tenant,
            Tenant.attivo.is_(True),
        )
    )
    tenant_obj = result.scalar_one_or_none()

    if tenant_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant non trovato o disattivato",
        )

    tenant_eliminato = await applica_policy_disattivazione_tenant(
        db,
        tenant_obj=tenant_obj,
    )
    if tenant_eliminato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant eliminato per mancato rinnovo oltre periodo di tregua",
        )

    return tenant_obj


async def prendi_tenant_con_accesso(
    tenant_obj: Annotated[Tenant, Depends(prendi_tenant_corrente)],
    utente_corrente: Annotated[Utente, Depends(prendi_utente_corrente)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    if not tenant_ha_accesso(tenant_obj):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso negato: piano non attivo o periodo di prova terminato",
        )

    risultato_ruolo = await db.execute(
        select(UtenteRuoloTenant.id).where(
            UtenteRuoloTenant.utente_id == utente_corrente.id,
            UtenteRuoloTenant.tenant_id == tenant_obj.id,
        ).limit(1)
    )
    ruolo_associazione = risultato_ruolo.scalar_one_or_none()
    if ruolo_associazione is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso negato: utente non associato al tenant richiesto",
        )

    return tenant_obj
