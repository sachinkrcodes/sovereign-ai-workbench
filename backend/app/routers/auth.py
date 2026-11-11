"""Login, logout and first-time setup."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import get_current_user, oauth2_scheme
from app.models import User
from app.schemas import AuthStatus, LoginResponse, SetupRequest, UserOut
from app.services import audit, auth as auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

BAD_LOGIN = "Incorrect email or password."


def _user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


@router.get("/status", response_model=AuthStatus)
def auth_status(db: Session = Depends(get_db)):
    """Public. Tells the web app whether the first admin still has to be created."""
    return AuthStatus(setup_required=_user_count(db) == 0)


@router.post("/setup", response_model=UserOut, status_code=201)
def first_time_setup(
    body: SetupRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_setup_token: Annotated[str | None, Header()] = None,
):
    """Create the very first admin. Works only while there are no users at all.
    If SETUP_TOKEN is configured (do this on a public server!), it must be sent in the
    X-Setup-Token header so a stranger cannot claim the admin account first."""
    if _user_count(db) > 0:
        raise HTTPException(status_code=409, detail="Setup is already done.")
    if settings.setup_token and x_setup_token != settings.setup_token:
        audit.record(db, action="auth.setup", status="denied", user_email=body.email.lower(),
                     detail={"reason": "bad setup token"}, request=request)
        raise HTTPException(status_code=403, detail="Invalid setup token.")
    user = auth_service.create_user(db, email=body.email, name=body.name, password=body.password, role="admin")
    audit.record(db, action="auth.setup", user=user, resource_type="user", resource_id=user.id, request=request)
    return user


@router.post("/login", response_model=LoginResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Use your email as `username`. In /docs you can also use the green Authorize button."""
    email = auth_service.normalise_email(form.username)

    recent_failures = audit.count_events(
        db,
        action="auth.login",
        status="failed",
        user_email=email,
        since_ts=audit.ts_minutes_ago(settings.login_window_minutes),
    )
    if recent_failures >= settings.login_max_failures:
        audit.record(db, action="auth.login", status="denied", user_email=email,
                     detail={"reason": "too many failed attempts"}, request=request)
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.")

    user = auth_service.authenticate(db, email, form.password)
    if user is None or not user.is_active:
        audit.record(db, action="auth.login", status="failed", user_email=email, request=request)
        raise HTTPException(status_code=401, detail=BAD_LOGIN, headers={"WWW-Authenticate": "Bearer"})

    token, expires_ts = auth_service.issue_token(db, user, settings.token_ttl_hours)
    audit.record(db, action="auth.login", user=user, request=request)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.token_ttl_hours * 3600,
        user=user,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke this token immediately."""
    if token:
        auth_service.revoke_token(db, token)
    audit.record(db, action="auth.logout", user=user, request=request)
