# =============================================================================
# backend/app/cli/inseminamento.py
# =============================================================================

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.sicurezza import hash_password
from app.models import Tenant, Utente, UtenteRuoloTenant, UtenteRuolo

app = typer.Typer(help="Comandi di seed/dati iniziali.")


async def _seed_tenant_and_admin(
    slug: str,
    nome_tenant: str,
    admin_email: str,
    admin_password: str,
) -> None:
    """Crea tenant + admin con ruolo SUPERUTENTE"""
    
    async with AsyncSessionLocal() as session:
        
        # ---- 1) Crea o trova Tenant ---------------------------------
        result = await session.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        tenant = result.scalar_one_or_none()

        if tenant is None:
            tenant = Tenant(
                slug=slug,
                nome=nome_tenant,
                attivo=True,
            )
            session.add(tenant)
            await session.flush()  # Genera tenant.id
            typer.secho(
                f"✅ Creato tenant '{slug}' (id={tenant.id})",
                fg=typer.colors.GREEN,
            )
        else:
            typer.echo(f"ℹ️  Tenant '{slug}' esiste già (id={tenant.id})")

        # ---- 2) Crea o trova Utente admin ---------------------------
        result = await session.execute(
            select(Utente).where(Utente.email == admin_email)
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            hashed = hash_password(admin_password)
            admin = Utente(
                tenant_id=tenant.id,
                nome="Admin",
                email=admin_email,
                hashed_password=hashed,
                attivo=True,
            )
            session.add(admin)
            await session.flush()  # Genera admin.id
            typer.secho(
                f"✅ Creato utente admin '{admin_email}' (id={admin.id})",
                fg=typer.colors.GREEN,
            )
        else:
            typer.echo(
                f"ℹ️  Utente admin '{admin_email}' esiste già (id={admin.id}, tenant_id={admin.tenant_id})"
            )

        # ---- 3) Assegna ruolo SUPERUTENTE ---------------------------
        result = await session.execute(
            select(UtenteRuoloTenant).where(
                UtenteRuoloTenant.utente_id == admin.id,
                UtenteRuoloTenant.tenant_id == tenant.id,
            )
        )
        ruolo_esistente = result.scalar_one_or_none()

        if ruolo_esistente is None:
            ruolo_admin = UtenteRuoloTenant(
                utente_id=admin.id,
                tenant_id=tenant.id,
                ruolo=UtenteRuolo.SUPERUTENTE,
            )
            session.add(ruolo_admin)
            await session.commit()
            typer.secho(
                f"✅ Ruolo SUPERUTENTE assegnato a '{admin_email}' per tenant '{slug}'",
                fg=typer.colors.GREEN,
            )
        else:
            typer.echo(
                f"ℹ️  Ruolo '{ruolo_esistente.ruolo}' già assegnato a '{admin_email}' per tenant '{slug}'"
            )

        typer.secho("\n🎉 Seed completato con successo!", fg=typer.colors.BRIGHT_GREEN, bold=True)


@app.command("tenant-admin")
def seed_tenant_and_admin(
    slug: Annotated[str, typer.Option(help="Slug tenant, es. 'demo'")] = "demo",
    nome_tenant: Annotated[
        str, typer.Option("--nome-tenant", help="Nome tenant, es. 'Tenant Demo'")
    ] = "Tenant Demo",
    admin_email: Annotated[
        str, typer.Option("--admin-email", help="Email admin")
    ] = "admin@demo.com",
    admin_password: Annotated[
        str, typer.Option("--admin-password", help="Password admin in chiaro")
    ] = "changeme",
) -> None:
    """
    Crea (se non esistono):
    1. Tenant con slug specificato
    2. Utente admin per quel tenant
    3. Ruolo SUPERUTENTE assegnato all'admin
    
    Esempio:
    python -m app.cli seed tenant-admin \
        --slug spotex \
        --nome-tenant "Spotex SRL" \
        --admin-email info@spotexsrl.it \
        --admin-password Password123!
    """
    asyncio.run(
        _seed_tenant_and_admin(slug, nome_tenant, admin_email, admin_password)
    )
