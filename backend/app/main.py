# =============================================================================
# backend/app/main
# =============================================================================

"""
Import di base ================================================================
"""

from fastapi.staticfiles import StaticFiles

import stripe  # ty:ignore[unresolved-import]

from app.core import settings

from app.core.security.sessione import gestore_sessioni

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.core import engine

from app.core.infrastructure.gestione_errori import registra_handler_globali

from app.routes import router as api_router

stripe.api_key = settings.stripe_secret_key

# =============================================================================

# -----------------------------------------------------------------------------

# =============================================================================

""" 
LifeSpanner = serve a definire in modo pulito cosa deve succedere =============
all’avvio dell’app e allo spegnimento =========================================
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
        """Hook di startup/shutdown.

        Mantieni il codice async-friendly: crea pool/client qui 
        (DB, Redis, ecc.) e chiudili all'arresto.
        """
        # --- STARTUP ---
        # Esempi di placeholder:
        # app.state.db = await create_db_pool(...)
        # app.state.redis = await create_redis_pool(...)
        app.state.engine = engine

        await gestore_sessioni.connessione()

        yield
        # --- SHUTDOWN ---
        # Esempi di placeholder:
        # await app.state.redis.aclose()
        # await app.state.db.close()
        await gestore_sessioni.disconnessione()

        await engine.dispose()

# =============================================================================

# -----------------------------------------------------------------------------

# =============================================================================

""" 
create_app() è “la fabbrica” che monta l’app completa =========================
(config + lifecycle + rotte) in modo pulito e scalabile =======================
"""

def create_app() -> FastAPI:
        app = FastAPI(
                title="TenantHawk - SaaS Template",
                version="0.1.0",
                lifespan=lifespan,
                docs_url="/docs",
                redoc_url="/redoc",
                openapi_url="/openapi.json",
        )
        
        app.mount("/static", StaticFiles(directory="app/static"), name="static")

        @app.middleware("http")
        async def aggiungi_header_sicurezza(request: Request, call_next):
                response = await call_next(request)

                response.headers.setdefault("X-Frame-Options", "DENY")
                response.headers.setdefault("X-Content-Type-Options", "nosniff")
                response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

                percorso = request.url.path
                docs_path = (
                        percorso.startswith("/docs")
                        or percorso.startswith("/redoc")
                        or percorso.startswith("/openapi")
                )
                if not docs_path:
                        response.headers.setdefault(
                                "Content-Security-Policy",
                                "default-src 'self'; "
                                "base-uri 'self'; "
                                "object-src 'none'; "
                                "frame-ancestors 'none'; "
                                "form-action 'self' https://checkout.stripe.com https://billing.stripe.com; "
                                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com; "
                                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
                                "img-src 'self' data: https:; "
                                "font-src 'self' data: https://fonts.gstatic.com; "
                                "connect-src 'self' https: wss:",
                        )

                return response

        # Healthcheck (async)
        @app.get("/health", tags=["system"])
        async def health() -> dict[str, str]:
                return {"status": "ok"}

        # Includi router (mantieni la resilienza mentre supporti le cartelle)
        #try:
        #        # Preferisci un singolo aggregatore di router api se lo hai
        #        from app.routes import router as api_router 
        #
        #        app.include_router(api_router)
        #except Exception:
        #        # Se il package routes non è ancora pronto, l'app gira comunque
        #        pass

        app.include_router(api_router)
        registra_handler_globali(app)

        return app


# =============================================================================

# -----------------------------------------------------------------------------

# =============================================================================

""" 
App ASGI per uvicorn/gunicorn =================================================
"""

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
