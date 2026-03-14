# =============================================================================
# backend/app/routes/admin/dashboard.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Request, Depends

from fastapi.responses import HTMLResponse

from app.core import templates

from app.core.permessi import prendi_ruolo_corrente

from app.core.tenancy import prendi_tenant_corrente

from app.core.auth import prendi_utente_corrente

from app.models import Tenant, Utente

router = APIRouter()

# -----------------------------------------------------------------------------
# DASHBOARD -------------------------------------------------------------------
# -----------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    tenant_obj: Tenant = Depends(prendi_tenant_corrente),
    utente_corrente: Utente = Depends(prendi_utente_corrente),
    ruolo_corrente: str = Depends(prendi_ruolo_corrente),
):
    return templates.TemplateResponse(
        "admin/dashboard/index.html",
        {
            "request": request,
            "tenant": tenant_obj,
            "utente": utente_corrente,
            "ruolo_corrente": ruolo_corrente,
        },
    )
