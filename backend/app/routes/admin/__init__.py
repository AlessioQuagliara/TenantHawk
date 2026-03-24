# =============================================================================
# backend/app/routes/admin/__init__.py
# =============================================================================

from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .impostazioni import router as impostazioni_router
from .sottoscrizioni import router as sottoscrizioni_router
from .users import router as users_router


router = APIRouter(prefix="/{tenant}/admin", tags=["admin"])
router.include_router(dashboard_router)
router.include_router(users_router)
router.include_router(sottoscrizioni_router)
router.include_router(impostazioni_router)


__all__ = ["router"]
