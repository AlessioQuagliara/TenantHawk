# =============================================================================
# backend/app/routes/__init__.py
# =============================================================================

from fastapi import APIRouter

from .auth import router as auth_router
from .admin import router as admin_router
from .core import router as controlli_router
from .stripe import router as stripe_router


router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(controlli_router)
router.include_router(stripe_router)

__all__ = ["router"]
