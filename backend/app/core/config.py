# =============================================================================
# backend/app/core/config.py
# =============================================================================

from __future__ import annotations

import re

from pydantic import field_validator

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
    frontend_base_url: str = "http://www.localhost:3000"

    # Diamo un taglio! (Mettiamo un limite a redis)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "5/minute"  # Max 5 login per IP al minuto

    # Importiamo le chiavi Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_base: str = ""
    stripe_price_pro: str = ""
    stripe_price_company: str = ""

    @field_validator("stripe_webhook_secret", mode="before")
    @classmethod
    def _normalizza_stripe_webhook_secret(cls, value: object) -> str:
        if value is None:
            return ""

        secret = str(value).strip().strip('"').strip("'")
        if not secret:
            return ""

        # Permette commenti inline nel .env (es: "... # SOLO TEST")
        if "#" in secret:
            secret = secret.split("#", 1)[0].strip()

        idx = secret.find("whsec_")
        if idx >= 0:
            secret = secret[idx:]

        # Se il secret e' stato accidentalmente concatenato due volte,
        # mantiene solo il primo.
        marker = "whsec_"
        first = secret.find(marker)
        second = secret.find(marker, first + len(marker)) if first >= 0 else -1
        if second > 0:
            secret = secret[:second]

        # Ripulisce caratteri finali non validi.
        secret = re.sub(r"[^A-Za-z0-9_]+$", "", secret).strip()
        return secret

settings = Settings()
