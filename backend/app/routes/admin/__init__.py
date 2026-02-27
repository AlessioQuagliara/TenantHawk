# =============================================================================
# backend/app/routes/admin/__init__.py
# =============================================================================

from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .users import router as users_router

router = APIRouter(prefix="/{tenant}/admin", tags=["admin"])
router.include_router(dashboard_router)
router.include_router(users_router)

__all__ = ["router"]