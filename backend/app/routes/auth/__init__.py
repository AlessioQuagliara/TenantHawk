# =============================================================================
# app/routes/auth/__init__.py
# =============================================================================

from fastapi import APIRouter

from .auth import router as auth_routes

router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(auth_routes)

__all__ = ["router"]