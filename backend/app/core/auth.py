# =============================================================================
# backend/app/core/auth.py
# =============================================================================

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.core.sessione import gestore_sessioni

from app.models import Utente, Tenant

# Nome cookie sessione
SESSION_COOKIE_NAME = "id_sessione_utente"


async def prendi_utente_corrente(
    id_sessione_utente: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> Utente:
    
    # ---- Verifica presenza cookie sessione ---------------------
    if not id_sessione_utente:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non autenticato - sessione mancante",
        )
    
    # ---- Recupera dati sessione da Redis ------------------------
    dati_sessione = await gestore_sessioni.ottieni_sessione(id_sessione_utente)
    
    if not dati_sessione:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessione scaduta o non valida",
        )
    
    id_utente = dati_sessione.get("id_utente")
    id_tenant = dati_sessione.get("id_tenant")
    
    # ---- Carica utente da DB con join tenant (1 query) ----------
    result = await db.execute(
        select(Utente)
        .join(Tenant, Utente.tenant_id == Tenant.id)
        .where(
            Utente.id == id_utente,
            Utente.tenant_id == id_tenant,
            Utente.attivo.is_(True),
            Tenant.attivo.is_(True),
        )
    )
    
    utente = result.scalar_one_or_none()
    
    # ---- Verifica utente valido ---------------------------------
    if not utente:
        # Sessione valida ma utente disabilitato/cancellato
        await gestore_sessioni.cancella_sessione(id_sessione_utente)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utente non più valido",
        )
    
    # ---- Refresh TTL sessione ad ogni richiesta -----------------
    await gestore_sessioni.ricarica_sessione(id_sessione_utente)
    
    return utente
