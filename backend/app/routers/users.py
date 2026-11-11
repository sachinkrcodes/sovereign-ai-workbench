"""User management (admins only)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.services import audit, auth as auth_service
from app import security

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _active_admin_count(db: Session, excluding: str | None = None) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
    if excluding:
        stmt = stmt.where(User.id != excluding)
    return db.scalar(stmt) or 0


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    if auth_service.get_user_by_email(db, body.email) is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    user = auth_service.create_user(db, email=body.email, name=body.name, password=body.password, role=body.role)
    audit.record(db, action="user.create", user=admin, resource_type="user", resource_id=user.id,
                 detail={"email": user.email, "role": user.role}, request=request)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    new_role = body.role if body.role is not None else user.role
    new_active = body.is_active if body.is_active is not None else user.is_active
    losing_admin = user.role == "admin" and user.is_active and (new_role != "admin" or not new_active)
    if losing_admin and _active_admin_count(db, excluding=user.id) == 0:
        raise HTTPException(status_code=409, detail="Cannot remove the last active admin.")

    changes: dict = {}
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active
    if body.password is not None:
        user.password_hash = security.hash_password(body.password)
        changes["password"] = "changed"
    db.commit()

    # Changing a password or switching a user off ends all of their sessions immediately.
    if body.password is not None or body.is_active is False:
        auth_service.revoke_all_tokens(db, user.id)

    audit.record(db, action="user.update", user=admin, resource_type="user", resource_id=user.id,
                 detail={"email": user.email, "changes": changes}, request=request)
    return user
