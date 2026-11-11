"""AI usage and cost reports."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import User
from app.schemas import UsageMe, UsageSummary
from app.services import usage

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


@router.get("/me", response_model=UsageMe)
def my_usage(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    today = usage.tokens_used_today(db, user.id)
    requests, total = usage.user_totals(db, user.id)
    unlimited = user.role == "admin"
    return UsageMe(
        today_tokens=today,
        daily_limit=None if unlimited else settings.daily_token_limit,
        remaining_today=None if unlimited else max(0, settings.daily_token_limit - today),
        total_requests=requests,
        total_tokens=total,
    )


@router.get("/summary", response_model=UsageSummary)
def usage_summary(
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_role("admin")),
):
    return usage.summary(db, settings, days)
