# =============================================================================
# backend/app/cli/inseminamento.py
# =============================================================================

from __future__ import annotations

import asyncio
import re
from typing import Annotated
from unicodedata import normalize

import typer
from sqlalchemy import select

from app.core.billing import crea_sottoscrizione_trial_tenant
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.sicurezza import hash_password
from app.models import (
    Sottoscrizione,
    Tenant,
    Utente,
    UtenteRuolo,
    UtenteRuoloTenant,
)

app = typer.Typer(help="Comandi seed/onboarding per tenant e utenti.")


async def _seed_tenant_and_admin(
    slug: str,
    nome_tenant: str,
    admin_name: str,
    admin_email: str,
    admin_password: str,
    with_trial: bool,
    trial_days: int,
) -> None:
    """Crea tenant + admin con ruolo SUPERUTENTE e trial opzionale."""

    ha_modifiche = False
    trial_esiste = False

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
            ha_modifiche = True
            typer.secho(
                f"[OK] Creato tenant '{slug}' (id={tenant.id})",
                fg=typer.colors.GREEN,
            )
        else:
            if not tenant.attivo:
                tenant.attivo = True
                ha_modifiche = True
                typer.echo(f"[INFO] Tenant '{slug}' riattivato (id={tenant.id})")
            typer.echo(f"[INFO] Tenant '{slug}' esiste gia' (id={tenant.id})")

        # ---- 2) Crea o trova Utente admin ---------------------------
        result = await session.execute(
            select(Utente).where(Utente.email == admin_email)
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            hashed = hash_password(admin_password)
            admin = Utente(
                tenant_id=tenant.id,
                nome=admin_name,
                email=admin_email,
                hashed_password=hashed,
                attivo=True,
            )
            session.add(admin)
            await session.flush()  # Genera admin.id
            ha_modifiche = True
            typer.secho(
                f"[OK] Creato utente admin '{admin_email}' (id={admin.id})",
                fg=typer.colors.GREEN,
            )
        else:
            if not admin.attivo:
                admin.attivo = True
                ha_modifiche = True
                typer.echo(f"[INFO] Utente '{admin_email}' riattivato")
            if not (admin.nome or "").strip():
                admin.nome = admin_name
                ha_modifiche = True
            typer.echo(
                f"[INFO] Utente admin '{admin_email}' esiste gia' (id={admin.id}, tenant_id={admin.tenant_id})"
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
            ha_modifiche = True
            typer.secho(
                f"[OK] Ruolo SUPERUTENTE assegnato a '{admin_email}' per tenant '{slug}'",
                fg=typer.colors.GREEN,
            )
        else:
            typer.echo(
                f"[INFO] Ruolo '{ruolo_esistente.ruolo}' gia' assegnato a '{admin_email}' per tenant '{slug}'"
            )

        # ---- 4) Crea trial billing opzionale -------------------------
        result = await session.execute(
            select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id).limit(1)
        )
        sottoscrizione = result.scalar_one_or_none()
        trial_esiste = sottoscrizione is not None

        if with_trial and sottoscrizione is None:
            await crea_sottoscrizione_trial_tenant(
                session,
                tenant_id=tenant.id,
                giorni_prova=trial_days,
            )
            ha_modifiche = True
            typer.secho(
                f"[OK] Creato trial ({trial_days} giorni) per tenant '{slug}'",
                fg=typer.colors.GREEN,
            )
        elif with_trial:
            typer.echo(
                "[INFO] Sottoscrizione gia' presente: nessun trial aggiuntivo creato."
            )
        else:
            typer.secho(
                "[WARN] Trial disabilitato: senza sottoscrizione valida l'area admin puo' risultare bloccata.",
                fg=typer.colors.YELLOW,
            )

        if ha_modifiche:
            await session.commit()

        login_url = f"{settings.app_base_url.rstrip('/')}/auth/login"
        dashboard_url = f"{settings.app_base_url.rstrip('/')}/{slug}/admin/dashboard"

        typer.secho("\n[READY] Onboarding completato.", fg=typer.colors.BRIGHT_GREEN, bold=True)
        typer.echo(f"Tenant: {slug}")
        typer.echo(f"Admin: {admin_email}")
        typer.echo(f"Login: {login_url}")
        typer.echo(f"Dashboard: {dashboard_url}")
        if not with_trial and not trial_esiste:
            typer.echo(
                "Nota: crea una sottoscrizione trial/attiva prima di entrare in dashboard."
            )


def _normalizza_slug_tenant(testo: str) -> str:
    testo_ascii = normalize("NFKD", testo).encode("ascii", "ignore").decode("ascii")
    testo_minuscolo = testo_ascii.lower().strip()
    testo_slug = re.sub(r"[^a-z0-9]+", "-", testo_minuscolo)
    return re.sub(r"-{2,}", "-", testo_slug).strip("-")


@app.command("tenant-admin")
def seed_tenant_and_admin(
    slug: Annotated[str, typer.Option(help="Slug tenant, es. 'demo'")] = "demo",
    nome_tenant: Annotated[
        str, typer.Option("--nome-tenant", help="Nome tenant, es. 'Tenant Demo'")
    ] = "Tenant Demo",
    admin_name: Annotated[
        str, typer.Option("--admin-name", help="Nome visualizzato admin")
    ] = "Admin",
    admin_email: Annotated[
        str, typer.Option("--admin-email", help="Email admin")
    ] = "admin@demo.com",
    admin_password: Annotated[
        str, typer.Option("--admin-password", help="Password admin in chiaro")
    ] = "changeme",
    with_trial: Annotated[
        bool,
        typer.Option(
            "--with-trial/--without-trial",
            help="Crea automaticamente trial billing se assente.",
        ),
    ] = True,
    trial_days: Annotated[
        int,
        typer.Option("--trial-days", min=1, help="Durata trial in giorni."),
    ] = 14,
) -> None:
    """
    Crea (se non esistono):
    1. Tenant con slug specificato
    2. Utente admin per quel tenant
    3. Ruolo SUPERUTENTE assegnato all'admin
    4. Trial billing (opzionale ma consigliato)
    
    Esempio:
    python -m app.cli seed tenant-admin \
        --slug spotex \
        --nome-tenant "Spotex SRL" \
        --admin-email info@spotexsrl.it \
        --admin-password Password123!
    """
    slug_finale = _normalizza_slug_tenant(slug)
    if not slug_finale:
        raise typer.BadParameter("Slug tenant non valido.")

    admin_email_finale = admin_email.strip().lower()
    if "@" not in admin_email_finale:
        raise typer.BadParameter("Email admin non valida.")

    asyncio.run(
        _seed_tenant_and_admin(
            slug=slug_finale,
            nome_tenant=nome_tenant.strip() or "Tenant Demo",
            admin_name=admin_name.strip() or "Admin",
            admin_email=admin_email_finale,
            admin_password=admin_password,
            with_trial=with_trial,
            trial_days=trial_days,
        )
    )


@app.command("quickstart")
def quickstart(
    tenant: Annotated[
        str,
        typer.Option("--tenant", help="Slug tenant rapido."),
    ] = "demo",
    nome_tenant: Annotated[
        str,
        typer.Option("--nome-tenant", help="Nome tenant."),
    ] = "Tenant Demo",
    admin_email: Annotated[
        str,
        typer.Option("--admin-email", help="Email admin."),
    ] = "admin@demo.com",
    admin_password: Annotated[
        str,
        typer.Option("--admin-password", help="Password admin."),
    ] = "changeme",
) -> None:
    """
    Shortcut onboarding locale: crea tenant + admin + ruolo + trial.
    """
    seed_tenant_and_admin(
        slug=tenant,
        nome_tenant=nome_tenant,
        admin_name="Admin",
        admin_email=admin_email,
        admin_password=admin_password,
        with_trial=True,
        trial_days=14,
    )
