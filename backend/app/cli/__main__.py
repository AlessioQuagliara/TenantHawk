# =============================================================================
# backend/app/cli/__main__.py
# =============================================================================

from __future__ import annotations

from . import app as main_app
from . import admin as admin_cli
from . import inseminamento as seed_cli


def run() -> None:
    main_app.add_typer(admin_cli.app, name="admin")
    main_app.add_typer(seed_cli.app, name="seed")
    main_app.command("quickstart")(seed_cli.quickstart)
    main_app()


if __name__ == "__main__":
    run()
