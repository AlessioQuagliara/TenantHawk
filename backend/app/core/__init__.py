# =============================================================================
# backend/app/core/__init__.py
# =============================================================================

from .config import settings
from .templates import templates
from .database import engine, Base

__all__ = ["settings", "templates", "engine", "Base", ]