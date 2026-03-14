# =============================================================================
# backend/app/core/config.py
# =============================================================================

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Legge da variabili d'ambiente e anche da .env (in dev)
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",  # ignora variabili sconosciute
    )

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    workers: int = 1

    # Importiamo il Database
    database_url: str = "sqlite:///./test.db"

    # Importiamo Redis
    redis_url: str = "redis://localhost:6379"

    # Importiamo la chiave segreta
    secret_key: str = "chiave_segreta"

    # Importo la chiave di Resend + Email
    resend_api_key: str = "re_chiave_presa_da_resend.com"
    reset_email_from: str = "SaaS Template <no-reply@linkbay-cms.com>"
    resend_dev_fallback_from: str = "SaaS Template <onboarding@resend.dev>"
    app_base_url: str = "http://admin.localhost:8000"

    # Diamo un taglio! (Mettiamo un limite a redis)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "5/minute"  # Max 5 login per IP al minuto

settings = Settings()
