# =============================================================================
# backend/app/core/tenancy.py
# =============================================================================

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path, status

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.core.database import get_db

from app.models import Tenant


async def prendi_tenant_corrente(
    tenant: Annotated[str, Path(..., description="Slug del tenant")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.ruoli_utenti))
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

    return tenant_obj
