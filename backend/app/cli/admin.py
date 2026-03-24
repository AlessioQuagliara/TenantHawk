# =============================================================================
# backend/app/cli/admin.py
# =============================================================================

from __future__ import annotations

from pathlib import Path
import textwrap
from typing import Annotated

import typer


app = typer.Typer(help="Comandi per l'area admin.")

ROOT = Path(__file__).resolve().parents[2]  # backend/
APP_DIR = ROOT / "app"
ROUTES_ADMIN_DIR = APP_DIR / "routes" / "admin"
TEMPLATES_ADMIN_DIR = APP_DIR / "templates" / "admin"
MODELS_DIR = APP_DIR / "models"
SCHEMAS_DIR = APP_DIR / "schemas"


def slugify(name: str) -> str:
    return (
        name.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


@app.command("create-module")
def create_admin_module(
    name: Annotated[str, typer.Argument(help="Nome del modulo, es. 'statistiche'")],
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
    Crea un modulo admin:

    - routes/admin/<name>.py
    - templates/admin/<name>/index.html
    - aggiorna routes/admin/__init__.py
    - opzionalmente: models/<name>.py
    - opzionalmente: schemas/<name>.py
    """
    slug = slugify(name)

    route_file = ROUTES_ADMIN_DIR / f"{slug}.py"
    template_dir = TEMPLATES_ADMIN_DIR / slug
    template_index = template_dir / "index.html"
    init_path = ROUTES_ADMIN_DIR / "__init__.py"

    if not init_path.exists():
        raise typer.Exit(f"__init__.py non trovato in {ROUTES_ADMIN_DIR}")

    if route_file.exists():
        raise typer.Exit(f"Il modulo admin '{slug}' esiste già.")

    # 1) ROUTE
    route_code = textwrap.dedent(
        f"""
        from __future__ import annotations

        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse

        from app.core.templates import templates


        router = APIRouter()


        @router.get("/{slug}", response_class=HTMLResponse)
        async def {slug}_page(request: Request):
            return templates.TemplateResponse(
                request,
                "admin/{slug}/index.html",
                {{}},
            )
        """
    ).lstrip()

    route_file.write_text(route_code, encoding="utf-8")

    # 2) TEMPLATE
    template_dir.mkdir(parents=True, exist_ok=True)
    template_index.write_text(
        textwrap.dedent(
            f"""\
            {{% extends "admin/base.html" %}}

            {{% block content %}}
            <h1 class="text-2xl font-semibold mb-4">Modulo {name}</h1>
            <p>Qui va la dashboard / pagina principale del modulo <strong>{name}</strong>.</p>
            {{% endblock %}}
            """
        ),
        encoding="utf-8",
    )

    # 3) MODEL opzionale
    if with_model:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_file = MODELS_DIR / f"{slug}.py"
        if model_file.exists():
            typer.secho(
                f"[WARN] Model '{model_file.name}' esiste già, salto.",
                fg=typer.colors.YELLOW,
            )
        else:
            model_code = textwrap.dedent(
                f"""
                from __future__ import annotations

                from sqlalchemy import Integer, String
                from sqlalchemy.orm import Mapped, mapped_column

                from app.core.database import Base


                class {slug.capitalize()}(Base):
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
                f"[WARN] Schema '{schema_file.name}' esiste già, salto.",
                fg=typer.colors.YELLOW,
            )
        else:
            schema_code = textwrap.dedent(
                f"""
                from __future__ import annotations

                from pydantic import BaseModel


                class {slug.capitalize()}Base(BaseModel):
                    name: str


                class {slug.capitalize()}Create({slug.capitalize()}Base):
                    pass


                class {slug.capitalize()}Read({slug.capitalize()}Base):
                    id: int

                    class Config:
                        from_attributes = True
                """
            ).lstrip()
            schema_file.write_text(schema_code, encoding="utf-8")
            typer.echo(f"  - {schema_file.relative_to(ROOT)}")

    # 5) Aggiorna routes/admin/__init__.py
    init_content = init_path.read_text(encoding="utf-8")

    import_line = f"from .{slug} import router as {slug}_router"
    include_line = f"router.include_router({slug}_router)"

    if import_line not in init_content:
        lines = init_content.splitlines()
        new_lines: list[str] = []
        inserted_import = False

        for line in lines:
            if (
                not inserted_import
                and line.strip().startswith("router = APIRouter")
            ):
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

    init_path.write_text(init_content, encoding="utf-8")

    typer.secho(f"[OK] Creato modulo admin '{name}'", fg=typer.colors.GREEN)
    typer.echo(f"  - {route_file.relative_to(ROOT)}")
    typer.echo(f"  - {template_index.relative_to(ROOT)}")
    typer.echo(f"  - aggiornato {init_path.relative_to(ROOT)}")
