"""Shared FastAPI dependencies: who is calling, what role they have, and usage limits."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.services import audit, auth as auth_service, usage

# auto_error=False so we can return our own clear 401 message
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

ROLES = ("viewer", "analyst", "admin")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES, start=1)}


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="Not authenticated. Log in to get a token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauthorized
    user = auth_service.find_user_by_token(db, token)
    if user is None:
        raise unauthorized
    request.state.user_id = user.id
    return user


def require_role(minimum: str):
    """Dependency factory: allow the caller only if their role is at least `minimum`
    (viewer < analyst < admin). Refusals are written to the audit log."""

    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum]:
            audit.record(
                db,
                action="access.denied",
                status="denied",
                user=user,
                detail={"path": request.url.path, "method": request.method, "needs": minimum},
                request=request,
            )
            raise HTTPException(status_code=403, detail=f"This action needs the '{minimum}' role.")
        return user

    return dependency


def enforce_token_budget(db: Session, user: User, settings: Settings, request: Request) -> None:
    """Block AI calls once a non-admin user has used their daily token allowance."""
    if user.role == "admin":
        return
    used = usage.tokens_used_today(db, user.id)
    if used >= settings.daily_token_limit:
        audit.record(
            db,
            action="usage.limit_reached",
            status="denied",
            user=user,
            detail={"used_today": used, "limit": settings.daily_token_limit},
            request=request,
        )
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow or ask an admin.",
        )
