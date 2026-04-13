# =============================================================================
# backend/app/core/sicurezza.py
# =============================================================================

from __future__ import annotations

import asyncio

from functools import partial

import bcrypt

# Limita la concorrenza di bcrypt per evitare saturazione del ThreadPoolExecutor
_bcrypt_semaphore = asyncio.Semaphore(10)


# ---- Hashing (sync, usato solo al seed/registrazione) ----------------------
def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


# ---- Verifica sync (da non usare nelle route async) ------------------------
def verifica_password(password_chiara: str, password_hashata: str) -> bool:
    return bcrypt.checkpw(
        password_chiara.encode("utf-8"),
        password_hashata.encode("utf-8"),
    )


# ---- Verifica async (usa questa nelle route FastAPI) -----------------------
async def verifica_password_async(
    password_chiara: str,
    password_hashata: str,
) -> bool:
    async with _bcrypt_semaphore:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(
                bcrypt.checkpw,
                password_chiara.encode("utf-8"),
                password_hashata.encode("utf-8"),
            ),
        )
