# =============================================================================
# backend/app/core/permessi.py
# =============================================================================

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.core.auth import prendi_utente_corrente

from app.core.tenancy import prendi_tenant_corrente

from app.models import Tenant, Utente, UtenteRuolo, UtenteRuoloTenant


def _valore_ruolo(ruolo: UtenteRuolo | str) -> str:
    if hasattr(ruolo, "value"):
        return str(ruolo.value)
    ruolo_str = str(ruolo).strip()
    if ruolo_str in UtenteRuolo.__members__:
        return UtenteRuolo[ruolo_str].value
    ruolo_str_lower = ruolo_str.lower()
    if ruolo_str_lower in {ruolo_enum.value for ruolo_enum in UtenteRuolo}:
        return ruolo_str_lower
    return ruolo_str


async def _ottieni_ruolo_utente_tenant(
    utente: Utente,
    tenant_id: int,
    db: AsyncSession,
) -> str | None:
    risultato = await db.execute(
        select(UtenteRuoloTenant.ruolo).where(
            UtenteRuoloTenant.utente_id == utente.id,
            UtenteRuoloTenant.tenant_id == tenant_id,
        ).limit(1)
    )
    ruolo = risultato.scalar_one_or_none()
    if ruolo is None:
        return None
    return _valore_ruolo(ruolo)


async def prendi_ruolo_corrente(
    utente: Utente = Depends(prendi_utente_corrente),
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    db: AsyncSession = Depends(get_db),
) -> str:
    ruolo_corrente = await _ottieni_ruolo_utente_tenant(utente, tenant_obj.id, db)
    if ruolo_corrente is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nessun ruolo assegnato per questo tenant",
        )
    return ruolo_corrente


async def _richiede_ruolo_impl(
    ruoli_permessi: list[UtenteRuolo],
    utente: Utente = Depends(prendi_utente_corrente),
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    db: AsyncSession = Depends(get_db),
):
    """
    Dependency per verificare che utente abbia almeno uno dei ruoli richiesti.
    
    Uso:
    @router.get("/admin/users")
    async def lista_utenti(
        _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE, UtenteRuolo.COLLABORATORE]))
    ):
        ...
    """
    
    ruolo_utente = await _ottieni_ruolo_utente_tenant(utente, tenant_obj.id, db)

    if ruolo_utente is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nessun ruolo assegnato per questo tenant",
        )

    ruoli_permessi_valori = [_valore_ruolo(ruolo) for ruolo in ruoli_permessi]

    # Verifica se ruolo utente è tra quelli permessi
    if ruolo_utente not in ruoli_permessi_valori:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Richiesto uno dei ruoli: {', '.join(ruoli_permessi_valori)}",
        )


def richiede_ruolo(ruoli_permessi: list[UtenteRuolo]):
    """Factory function that returns a dependency for checking required roles."""
    async def dependency(
        utente: Utente = Depends(prendi_utente_corrente),
        tenant_obj: Tenant = Depends(prendi_tenant_corrente),
        db: AsyncSession = Depends(get_db),
    ):
        return await _richiede_ruolo_impl(ruoli_permessi, utente, tenant_obj, db)
    return dependency


# Shortcut per SUPERUTENTE only
async def solo_superutente(
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
):
    """Dependency che richiede SUPERUTENTE"""
    pass
