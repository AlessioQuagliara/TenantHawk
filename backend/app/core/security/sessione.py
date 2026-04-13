# =============================================================================
# backend/app/core/sessione.py
# =============================================================================

from __future__ import annotations

import json 

import secrets

from datetime import timedelta

from typing import Any

import redis.asyncio as asredit

from app.core.infrastructure.config import settings

class SessionManager:

    # Manager sessioni Redis con TTL automatico
    def __init__(self):
        self.redis: asredit.Redis | None = None
        self._ttl = timedelta(hours=24) # La sessione scade in 24 ore

    # Connessione pool Redis all'avvio dell'app
    async def connessione(self):
        self.redis = await asredit.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )

    # Chiusura connessioni Redis allo spegnimento
    async def disconnessione(self):
        if self.redis:
            await self.redis.close()

    # Crea nuova sessione
    async def crea_sessione(
        self,
        id_utente: int,
        id_tenant: int,
        **extra_data: Any,
        ) -> str:
        id_sessione_utente = secrets.token_urlsafe(32)

        data_sessioni ={
            "id_utente": id_utente,
            "id_tenant": id_tenant,
            **extra_data,
        }
        
        if self.redis:
            await self.redis.setex(
                f"sessione:{id_sessione_utente}",
                self._ttl,
                json.dumps(data_sessioni),
            )

        return id_sessione_utente

    # Recupera dati sessione, Manda None se scaduta o non esiste
    async def ottieni_sessione(self, id_sessione_utente: str) -> dict[str,Any] | None:
        if not self.redis:
            return None
        data = await self.redis.get(f"sessione:{id_sessione_utente}")
        return json.loads(data) if data else None

    # Estende TTL sessione (che chiama ad ogni richiesta dopo auth)
    async def ricarica_sessione(self, id_sessione_utente: str) -> bool:
        if not self.redis:
            return False
        return await self.redis.expire(f"sessione:{id_sessione_utente}", self._ttl)

    # Elimina sessione (Logout)
    async def cancella_sessione(self, id_sessione_utente: str) -> bool:
        if not self.redis:
            return False
        return bool(await self.redis.delete(f"sessione:{id_sessione_utente}"))

# Istanza globale
gestore_sessioni = SessionManager()