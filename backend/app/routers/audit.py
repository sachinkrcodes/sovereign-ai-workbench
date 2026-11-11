"""Audit log (admins only): who did what, and a check that nobody tampered with it."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_role
from app.models import AuditEvent, User
from app.schemas import AuditList, AuditVerifyOut
from app.services import audit as audit_service

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("", response_model=AuditList)
def list_events(
    action: Annotated[str | None, Query(max_length=60)] = None,
    user_email: Annotated[str | None, Query(max_length=254)] = None,
    status: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    conditions = []
    if action:
        conditions.append(AuditEvent.action == action)
    if user_email:
        conditions.append(AuditEvent.user_email == user_email.strip().lower())
    if status:
        conditions.append(AuditEvent.status == status)
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions)) or 0
    items = db.scalars(
        select(AuditEvent).where(*conditions).order_by(AuditEvent.id.desc()).offset(offset).limit(limit)
    ).all()
    return AuditList(items=items, total=total, limit=limit, offset=offset)


@router.get("/verify", response_model=AuditVerifyOut)
def verify(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    """Re-check the whole hash chain. `valid: false` means a row was edited or removed."""
    return audit_service.verify_database(db)
