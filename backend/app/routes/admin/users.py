# =============================================================================
# backend/app/routes/admin/users.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import status

from app.core import templates
from app.core.pagination import Pagination

router = APIRouter()

# -----------------------------------------------------------------------------
# USERS -----------------------------------------------------------------------
# -----------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_index(request: Request):
    """Pagina principale di gestione utenti (carica il template con filtri e tabella vuota)."""
    from app.core.pagination import Pagination
    return templates.TemplateResponse(
        "admin/users/index.html",
        {
            "request": request,
            "users": [],
            "pagination": Pagination(1, 10, 0),
            "current_filters": {},
            "search_value": ""
        }
    )

# -----------------------------------------------------------------------------
# TABELLA USERS ---------------------------------------------------------------
# -----------------------------------------------------------------------------

@router.get("/users/table", response_class=HTMLResponse)
async def users_table(
    request: Request,
    page: int = Query(1, ge=1),
    search: str = Query(""),
    per_page: int = Query(10, ge=1, le=100),
    filter_role: str = Query("", alias="filter_role"),
    filter_status: str = Query("", alias="filter_status"),
):
    """
    Restituisce il partial della tabella utenti (inclusa paginazione).
    I dati reali verranno prelevati dal database in modo asincrono.
    """
    # --- ESEMPIO di query con SQLAlchemy 2.0 async ---
    # async with async_session() as session:
    #     # Costruzione query base
    #     stmt = select(User)
    #
    #     # Applicazione filtri
    #     if search:
    #         stmt = stmt.where(
    #             User.name.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
    #         )
    #     if filter_role:
    #         stmt = stmt.where(User.role == filter_role)
    #     if filter_status:
    #         stmt = stmt.where(User.status == filter_status)
    #
    #     # Conteggio totale (per paginazione)
    #     count_stmt = select(func.count()).select_from(User).where(stmt.whereclause)
    #     total = await session.scalar(count_stmt) or 0
    #
    #     # Esecuzione paginata
    #     offset = (page - 1) * per_page
    #     result = await session.execute(stmt.offset(offset).limit(per_page))
    #     users = result.scalars().all()
    #
    #     # Trasforma gli oggetti in dict (se necessario, altrimenti usa direttamente gli oggetti)
    #     users_list = []
    #     for user in users:
    #         users_list.append({
    #             "id": user.id,
    #             "name": user.name,
    #             "email": user.email,
    #             "role": user.role,
    #             "status": user.status,
    #             "created_at": user.created_at.strftime("%d/%m/%Y") if user.created_at else "-",
    #         })

    # PER ORA: placeholder per dati vuoti (nessun fake)
    users_list = []
    total = 0

    # Crea oggetto paginazione
    pagination = Pagination(page, per_page, total)

    # Prepara filtri correnti per il template
    current_filters = {}
    if filter_role:
        current_filters["filter_role"] = filter_role
    if filter_status:
        current_filters["filter_status"] = filter_status

    return templates.TemplateResponse(
        "admin/partials/table.html",
        {
            "request": request,
            "users": users_list,
            "pagination": pagination,
            "current_filters": current_filters,
            "search_value": search,
        }
    )


# --- CRUD con modali (placeholder) ---

@router.get("/users/new", response_class=HTMLResponse)
async def user_new_form(request: Request):
    """Mostra form per creazione nuovo utente (modale)."""
    # Restituisce un frammento HTML (es. form)
    return templates.TemplateResponse(
        "admin/users/partials/user_form.html",
        {"request": request, "user": None}
    )


@router.post("/users", response_class=HTMLResponse)
async def user_create(request: Request):
    """Crea un nuovo utente (da form)."""
    # Estrai dati dal form (request.form())
    # Salva nel DB
    # Dopo il salvataggio, restituisci la tabella aggiornata (Redirect o HTML partial)
    # return RedirectResponse(url="/admin/users/table?page=1", status_code=status.HTTP_303_SEE_OTHER)
    pass


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
async def user_edit_form(request: Request, user_id: int):
    """Mostra form di modifica utente (modale)."""
    # Carica utente dal DB e restituisci form precompilato
    pass


@router.put("/users/{user_id}", response_class=HTMLResponse)
async def user_update(request: Request, user_id: int):
    """Aggiorna utente esistente."""
    pass


@router.delete("/users/{user_id}", response_class=HTMLResponse)
async def user_delete(request: Request, user_id: int):
    """Elimina utente."""
    # Dopo eliminazione, restituisci tabella aggiornata (o messaggio toast)
    pass


@router.post("/users/bulk-delete", response_class=HTMLResponse)
async def users_bulk_delete(request: Request, ids: list[int] = Form(...)):
    """Eliminazione multipla di utenti."""
    # ids è una lista di ID (dalle checkbox)
    # Esegui eliminazione e restituisci tabella aggiornata
    pass