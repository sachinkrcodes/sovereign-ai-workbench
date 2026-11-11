"""Tamper-evident audit log.

Each event stores the hash of the previous event plus its own content. Editing or deleting
any middle row breaks the chain, and GET /api/v1/audit/verify finds the first broken row.
(Honest limit: deleting the newest rows cannot be detected from inside the database alone;
save the `head_hash` shown by verify somewhere safe to detect that too.)"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, User

logger = logging.getLogger("app.audit")

GENESIS_HASH = "0" * 64
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
MAX_DETAIL_TEXT = 200


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


def ts_minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(_TS_FORMAT)


def clip(text: str, limit: int = MAX_DETAIL_TEXT) -> str:
    """Keep audit entries small: long user text is shortened."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _content(event) -> dict:
    return {
        "ts": event.ts,
        "user_id": event.user_id,
        "user_email": event.user_email,
        "action": event.action,
        "status": event.status,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "detail": event.detail or {},
        "ip": event.ip,
        "request_id": event.request_id,
    }


def compute_hash(prev_hash: str, content: dict) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    action: str,
    status: str = "success",
    user: User | None = None,
    user_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict | None = None,
    request=None,
) -> None:
    """Append one event. Never raises: a logging problem must not break the user's request.
    NOTE: commits the session, so call it after the main work has been committed."""
    try:
        last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
        prev_hash = last.event_hash if last else GENESIS_HASH
        event = AuditEvent(
            ts=now_ts(),
            user_id=user.id if user else None,
            user_email=user.email if user else user_email,
            action=action,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail or {},
            ip=(request.client.host if request is not None and request.client else None),
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            prev_hash=prev_hash,
            event_hash="",
        )
        event.event_hash = compute_hash(prev_hash, _content(event))
        db.add(event)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not write audit event %s", action)


def verify_chain(events) -> dict:
    """Check a sequence of events (oldest first). Returns a summary dict."""
    expected_prev = GENESIS_HASH
    count = 0
    for event in events:
        count += 1
        if event.prev_hash != expected_prev or compute_hash(event.prev_hash, _content(event)) != event.event_hash:
            return {"valid": False, "events_checked": count, "first_invalid_id": event.id, "head_hash": None}
        expected_prev = event.event_hash
    return {
        "valid": True,
        "events_checked": count,
        "first_invalid_id": None,
        "head_hash": expected_prev if count else None,
    }


def verify_database(db: Session) -> dict:
    return verify_chain(db.scalars(select(AuditEvent).order_by(AuditEvent.id)).all())


def count_events(db: Session, *, action: str, status: str, user_email: str, since_ts: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == action,
                AuditEvent.status == status,
                AuditEvent.user_email == user_email,
                AuditEvent.ts >= since_ts,
            )
        )
        or 0
    )
