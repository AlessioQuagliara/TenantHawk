# =============================================================================
# backend/app/cli/admin.py
# =============================================================================

from __future__ import annotations

from pathlib import Path
import re
import textwrap
from typing import Annotated
from unicodedata import normalize

import typer


app = typer.Typer(help="Comandi per generare e gestire moduli admin.")

ROOT = Path(__file__).resolve().parents[2]  # backend/
APP_DIR = ROOT / "app"
ROUTES_ADMIN_DIR = APP_DIR / "routes" / "admin"
TEMPLATES_ADMIN_DIR = APP_DIR / "templates" / "admin"
MODELS_DIR = APP_DIR / "models"
SCHEMAS_DIR = APP_DIR / "schemas"


def slugify(name: str) -> str:
    testo_ascii = normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    testo = testo_ascii.lower().strip()
    testo = re.sub(r"[^a-z0-9]+", "_", testo)
    return re.sub(r"_+", "_", testo).strip("_")


def to_class_name(slug: str) -> str:
    parti = [p for p in slug.split("_") if p]
    if not parti:
        return "ModuloAdmin"
    return "".join(parte.capitalize() for parte in parti)


def to_label(slug: str) -> str:
    return slug.replace("_", " ").strip().title() or "Nuovo Modulo"


def _build_route_code(
    *,
    slug: str,
    superuser_only: bool,
) -> str:
    if superuser_only:
        return textwrap.dedent(
            f"""
            from __future__ import annotations

            from fastapi import APIRouter, Depends, Request
            from fastapi.responses import HTMLResponse

            from app.core.security.auth import prendi_utente_corrente
            from app.core.security.permessi import prendi_ruolo_corrente, richiede_ruolo
            from app.core.infrastructure.templates import templates
            from app.core.tenancy import prendi_tenant_con_accesso
            from app.models import Tenant, Utente, UtenteRuolo


            router = APIRouter()


            @router.get("/{slug}", response_class=HTMLResponse)
            async def {slug}_page(
                request: Request,
                tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
                utente_corrente: Utente = Depends(prendi_utente_corrente),
                ruolo_corrente: str = Depends(prendi_ruolo_corrente),
                _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE])),
            ):
                return templates.TemplateResponse(
                    request,
                    "admin/{slug}/index.html",
                    {{
                        "tenant": tenant_obj,
                        "utente": utente_corrente,
                        "ruolo_corrente": ruolo_corrente,
                    }},
                )
            """
        ).lstrip()

    return textwrap.dedent(
        f"""
        from __future__ import annotations

        from fastapi import APIRouter, Depends, Request
        from fastapi.responses import HTMLResponse

        from app.core.security.auth import prendi_utente_corrente
        from app.core.security.permessi import prendi_ruolo_corrente
        from app.core.infrastructure.templates import templates
        from app.core.tenancy import prendi_tenant_con_accesso
        from app.models import Tenant, Utente


        router = APIRouter()


        @router.get("/{slug}", response_class=HTMLResponse)
        async def {slug}_page(
            request: Request,
            tenant_obj: Tenant = Depends(prendi_tenant_con_accesso),
            utente_corrente: Utente = Depends(prendi_utente_corrente),
            ruolo_corrente: str = Depends(prendi_ruolo_corrente),
        ):
            return templates.TemplateResponse(
                request,
                "admin/{slug}/index.html",
                {{
                    "tenant": tenant_obj,
                    "utente": utente_corrente,
                    "ruolo_corrente": ruolo_corrente,
                }},
            )
        """
    ).lstrip()


def _build_template_code(*, label: str, slug: str) -> str:
    return textwrap.dedent(
        f"""\
        {{% extends "admin/base.html" %}}

        {{% block admin_heading %}}{label}{{% endblock %}}

        {{% block admin_content %}}
        <section class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6">
          <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100">{label}</h1>
          <p class="mt-2 text-sm text-gray-600 dark:text-gray-300">
            Modulo <strong>{slug}</strong> creato con CLI. Personalizza qui widget, tabelle e azioni.
          </p>
        </section>
        {{% endblock %}}
        """
    )


def _upsert_admin_router_init(init_path: Path, slug: str) -> None:
    init_content = init_path.read_text(encoding="utf-8")

    import_line = f"from .{slug} import router as {slug}_router"
    include_line = f"router.include_router({slug}_router)"

    if import_line not in init_content:
        lines = init_content.splitlines()
        new_lines: list[str] = []
        inserted_import = False

        for line in lines:
            if not inserted_import and line.strip().startswith("router = APIRouter"):
                new_lines.append(import_line)
                inserted_import = True
            new_lines.append(line)

        if not inserted_import:
            new_lines.append(import_line)

        init_content = "\n".join(new_lines)

    if include_line not in init_content:
        lines = init_content.splitlines()
        new_lines = []
        inserted_include = False

        for line in lines:
            if not inserted_include and line.strip().startswith("__all__"):
                new_lines.append(include_line)
                inserted_include = True
            new_lines.append(line)

        if not inserted_include:
            new_lines.append(include_line)

        init_content = "\n".join(new_lines)

    init_path.write_text(init_content + "\n", encoding="utf-8")


@app.command("create-module")
def create_admin_module(
    name: Annotated[str, typer.Argument(help="Nome modulo, es. 'statistiche-vendite'")],
    label: Annotated[
        str | None,
        typer.Option("--label", help="Titolo UI (default: dal nome modulo)."),
    ] = None,
    superuser_only: Annotated[
        bool,
        typer.Option(
            "--superuser-only/--all-roles",
            help="Protegge il modulo per soli superutenti.",
        ),
    ] = False,
    with_model: Annotated[
        bool,
        typer.Option("--with-model", help="Crea anche un file model SQLAlchemy."),
    ] = False,
    with_schema: Annotated[
        bool,
        typer.Option("--with-schema", help="Crea anche un file schema Pydantic."),
    ] = False,
) -> None:
    """
    Crea un modulo admin tenant-aware:

    - routes/admin/<name>.py
    - templates/admin/<name>/index.html
    - aggiorna routes/admin/__init__.py
    - opzionalmente: models/<name>.py
    - opzionalmente: schemas/<name>.py
    """
    slug = slugify(name)
    if not slug:
        raise typer.BadParameter("Nome modulo non valido.")

    final_label = (label or "").strip() or to_label(slug)
    class_name = to_class_name(slug)

    route_file = ROUTES_ADMIN_DIR / f"{slug}.py"
    template_dir = TEMPLATES_ADMIN_DIR / slug
    template_index = template_dir / "index.html"
    init_path = ROUTES_ADMIN_DIR / "__init__.py"

    if not init_path.exists():
        raise typer.Exit(f"__init__.py non trovato in {ROUTES_ADMIN_DIR}")

    if route_file.exists():
        raise typer.Exit(f"Il modulo admin '{slug}' esiste gia'.")

    # 1) ROUTE
    route_file.write_text(
        _build_route_code(slug=slug, superuser_only=superuser_only),
        encoding="utf-8",
    )

    # 2) TEMPLATE
    template_dir.mkdir(parents=True, exist_ok=True)
    template_index.write_text(
        _build_template_code(label=final_label, slug=slug),
        encoding="utf-8",
    )

    # 3) MODEL opzionale
    if with_model:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_file = MODELS_DIR / f"{slug}.py"
        if model_file.exists():
            typer.secho(
                f"[WARN] Model '{model_file.name}' esiste gia', salto.",
                fg=typer.colors.YELLOW,
            )
        else:
            model_code = textwrap.dedent(
                f"""
                from __future__ import annotations

                from sqlalchemy import Integer, String
                from sqlalchemy.orm import Mapped, mapped_column

                from app.core.infrastructure.database import Base


                class {class_name}(Base):
                    __tablename__ = "{slug}"

                    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
                    name: Mapped[str] = mapped_column(String(255), nullable=False)
                """
            ).lstrip()
            model_file.write_text(model_code, encoding="utf-8")
            typer.echo(f"  - {model_file.relative_to(ROOT)}")

    # 4) SCHEMA opzionale
    if with_schema:
        SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
        schema_file = SCHEMAS_DIR / f"{slug}.py"
        if schema_file.exists():
            typer.secho(
                f"[WARN] Schema '{schema_file.name}' esiste gia', salto.",
                fg=typer.colors.YELLOW,
            )
        else:
            schema_code = textwrap.dedent(
                f"""
                from __future__ import annotations

                from pydantic import BaseModel


                class {class_name}Base(BaseModel):
                    name: str


                class {class_name}Create({class_name}Base):
                    pass


                class {class_name}Read({class_name}Base):
                    id: int

                    class Config:
                        from_attributes = True
                """
            ).lstrip()
            schema_file.write_text(schema_code, encoding="utf-8")
            typer.echo(f"  - {schema_file.relative_to(ROOT)}")

    # 5) Aggiorna routes/admin/__init__.py
    _upsert_admin_router_init(init_path, slug)

    typer.secho(f"[OK] Creato modulo admin '{final_label}' ({slug})", fg=typer.colors.GREEN)
    typer.echo(f"  - {route_file.relative_to(ROOT)}")
    typer.echo(f"  - {template_index.relative_to(ROOT)}")
    typer.echo(f"  - aggiornato {init_path.relative_to(ROOT)}")
    if superuser_only:
        typer.echo("  - accesso: solo SUPERUTENTE")
    else:
        typer.echo("  - accesso: tutti i ruoli del tenant autenticati")


@app.command("list-modules")
def list_modules() -> None:
    """
    Elenca i moduli admin presenti in routes/admin.
    """
    moduli = sorted(
        path.stem
        for path in ROUTES_ADMIN_DIR.glob("*.py")
        if path.name != "__init__.py"
    )

    if not moduli:
        typer.echo("Nessun modulo admin trovato.")
        return

    typer.echo("Moduli admin disponibili:")
    for modulo in moduli:
        typer.echo(f"- {modulo}")
