# =============================================================================
# backend/app/routes/admin/dashboard.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core import templates

router = APIRouter()

# -----------------------------------------------------------------------------
# DASHBOARD -------------------------------------------------------------------
# -----------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(
        "admin/dashboard/index.html",
        {"request": request},
    )