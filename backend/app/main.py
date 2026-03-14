# =============================================================================
# backend/app/main
# =============================================================================

"""
Import di base ================================================================
"""

from fastapi.staticfiles import StaticFiles

from app.core import settings

from app.core.sessione import gestore_sessioni

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import engine

from app.routes import router as api_router

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
                title="SaaS_Template",
                version="0.1.0",
                lifespan=lifespan,
                docs_url="/docs",
                redoc_url="/redoc",
                openapi_url="/openapi.json",
        )
        
        app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
