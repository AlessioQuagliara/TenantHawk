# =============================================================================
# backend/app/core/config.py
# =============================================================================

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Legge da variabili d'ambiente e anche da .env (in dev)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",  # ignora variabili sconosciute
    )

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    workers: int = 1

    # Importiamo il Database
    database_url: str

settings = Settings()