"""AI usage tracking (tokens), daily limits and cost reports."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import UsageEvent, User
from app.services.audit import now_ts


def record_usage(
    db: Session,
    *,
    user: User,
    kind: str,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: int,
    ref: str | None = None,
) -> None:
    db.add(
        UsageEvent(
            ts=now_ts(),
            user_id=user.id,
            kind=kind,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration_ms=duration_ms,
            ref=ref,
        )
    )
    db.commit()


def _utc_day_start() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00.000000Z")


def tokens_used_today(db: Session, user_id: str) -> int:
    return (
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.total_tokens), 0)).where(
                UsageEvent.user_id == user_id, UsageEvent.ts >= _utc_day_start()
            )
        )
        or 0
    )


def user_totals(db: Session, user_id: str) -> tuple[int, int]:
    row = db.execute(
        select(func.count(UsageEvent.id), func.coalesce(func.sum(UsageEvent.total_tokens), 0)).where(
            UsageEvent.user_id == user_id
        )
    ).one()
    return int(row[0]), int(row[1])


def equivalent_cloud_cost(prompt_tokens: int, completion_tokens: int, settings: Settings) -> float:
    cost = (
        prompt_tokens * settings.cloud_price_per_million_prompt
        + completion_tokens * settings.cloud_price_per_million_completion
    ) / 1_000_000
    return round(cost, 6)


def summary(db: Session, settings: Settings, days: int = 7) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    in_range = UsageEvent.ts >= since

    totals = db.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
        ).where(in_range)
    ).one()
    requests, prompt, completion, total = (int(x) for x in totals)

    tokens = func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens")
    by_user = [
        {"email": email, "requests": int(count), "total_tokens": int(tok)}
        for email, count, tok in db.execute(
            select(User.email, func.count(UsageEvent.id), tokens)
            .join(User, User.id == UsageEvent.user_id)
            .where(in_range)
            .group_by(User.email)
            .order_by(tokens.desc())
        ).all()
    ]
    day = func.substr(UsageEvent.ts, 1, 10).label("day")
    by_day = [
        {"day": d, "requests": int(count), "total_tokens": int(tok)}
        for d, count, tok in db.execute(
            select(day, func.count(UsageEvent.id), tokens).where(in_range).group_by(day).order_by(day)
        ).all()
    ]
    by_kind = [
        {"kind": kind, "requests": int(count), "total_tokens": int(tok)}
        for kind, count, tok in db.execute(
            select(UsageEvent.kind, func.count(UsageEvent.id), tokens)
            .where(in_range)
            .group_by(UsageEvent.kind)
            .order_by(tokens.desc())
        ).all()
    ]
    return {
        "days": days,
        "requests": requests,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "actual_cost_usd": 0.0,  # models run on your own hardware
        "equivalent_cloud_cost_usd": equivalent_cloud_cost(prompt, completion, settings),
        "pricing_note": "Illustrative hosted-API rates (set in settings); your local models cost $0 per request.",
        "by_user": by_user,
        "by_day": by_day,
        "by_kind": by_kind,
    }
