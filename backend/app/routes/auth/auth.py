# =============================================================================
# backend/app/routes/auth/auth.py
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core import templates

router = APIRouter()


# -----------------------------------------------------------------------------
# LOGIN -----------------------------------------------------------------------
# -----------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str | None = None):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "next": next or "/"},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    # TODO: replace with real auth.
    ok = (email == "demo@demo.com" and password == "demo")

    if not ok:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "next": next, "error": "Credenziali non valide"},
            status_code=400,
        )

    resp = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        "session",
        "fake-session-token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return resp


# -----------------------------------------------------------------------------
# LOGOUT
# -----------------------------------------------------------------------------

@router.post("/logout")
async def logout_submit():
    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("session")
    return resp


# -----------------------------------------------------------------------------
# SIGN-UP (registrazione)
# -----------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request})


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if password != password2:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Le password non coincidono"},
            status_code=400,
        )

    # TODO: create user + send verification email (async job)
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# PASSWORD RECOVERY (richiesta reset)
# -----------------------------------------------------------------------------

@router.get("/password-recovery", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/password-recovery", response_class=HTMLResponse)
async def forgot_password_submit(request: Request, email: str = Form(...)):
    # TODO: generate token + send email (async job)
    # Security: always neutral response
    return templates.TemplateResponse(
        "auth/forgot_password.html",
        {"request": request, "ok": "Se l’email esiste, riceverai un link di reset."},
    )


# -----------------------------------------------------------------------------
# RESET PASSWORD (con token)
# -----------------------------------------------------------------------------

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str):
    return templates.TemplateResponse(
        "auth/reset_password.html",
        {"request": request, "token": token},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if password != password2:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {"request": request, "token": token, "error": "Le password non coincidono"},
            status_code=400,
        )

    # TODO: validate token + change password
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# CONFIRM PASSWORD (reauth)
# -----------------------------------------------------------------------------

@router.get("/confirm-password", response_class=HTMLResponse)
async def confirm_password_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        "auth/confirm_password.html",
        {"request": request, "next": next},
    )


@router.post("/confirm-password", response_class=HTMLResponse)
async def confirm_password_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form("/"),
):
    # TODO: verify current user's password
    ok = (password == "demo")

    if not ok:
        return templates.TemplateResponse(
            "auth/confirm_password.html",
            {"request": request, "next": next, "error": "Password errata"},
            status_code=400,
        )

    return RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# 2FA (TOTP)
# -----------------------------------------------------------------------------

@router.get("/2fa", response_class=HTMLResponse)
async def two_factor_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        "auth/two_factor.html",
        {"request": request, "next": next},
    )


@router.post("/2fa", response_class=HTMLResponse)
async def two_factor_submit(
    request: Request,
    code: str = Form(...),
    next: str = Form("/"),
):
    # TODO: validate TOTP code
    ok = (code == "123456")

    if not ok:
        return templates.TemplateResponse(
            "auth/two_factor.html",
            {"request": request, "next": next, "error": "Codice non valido"},
            status_code=400,
        )

    resp = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        "session",
        "fake-session-token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return resp