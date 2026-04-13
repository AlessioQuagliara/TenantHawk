# =============================================================================
# backend/app/core/database.py
# =============================================================================


from sqlalchemy.ext.asyncio import (
    create_async_engine, 
    async_sessionmaker, 
    AsyncSession,
)

from sqlalchemy.orm import declarative_base

from app.core.infrastructure.config import settings

from typing import AsyncGenerator

# Definisco Base
Base = declarative_base()

# Creazione motore "engine" del db con pool di connessioni
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=5,       
    max_overflow=5,    
    pool_timeout=30,
)

# Struttura per creare sessioni asincrone per richiesta

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

# Dipendenza FastAPI che fornisce una AsyncSession per ogni richiesta
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()