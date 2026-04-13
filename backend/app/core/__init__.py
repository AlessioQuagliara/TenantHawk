# =============================================================================
# backend/app/core/__init__.py
# =============================================================================

from .infrastructure.config import settings
from .infrastructure.database import Base, engine
from .infrastructure.templates import templates

__all__ = ["settings", "templates", "engine", "Base"]
