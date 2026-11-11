"""Users, passwords and login sessions (tokens)."""

import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import security
from app.models import AuthToken, User

# Used when the email is unknown, so "no such user" takes as long as "wrong password"
# (stops attackers from discovering which emails are registered by timing).
_DUMMY_HASH = security.hash_password("dummy-password-for-timing", n=2**10)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, *, email: str, name: str, password: str, role: str) -> User:
    user = User(
        email=normalise_email(email),
        name=name.strip(),
        password_hash=security.hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalise_email(email)))


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None:
        security.verify_password(password, _DUMMY_HASH)
        return None
    if not security.verify_password(password, user.password_hash):
        return None
    return user


def issue_token(db: Session, user: User, ttl_hours: int) -> tuple[str, int]:
    raw = security.new_token()
    now = int(time.time())
    expires = now + ttl_hours * 3600
    db.add(AuthToken(user_id=user.id, token_hash=security.hash_token(raw), created_ts=now, expires_ts=expires))
    db.commit()
    return raw, expires


def find_user_by_token(db: Session, raw_token: str) -> User | None:
    row = db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == security.hash_token(raw_token),
            AuthToken.revoked.is_(False),
            AuthToken.expires_ts > int(time.time()),
        )
    )
    if row is None:
        return None
    user = db.get(User, row.user_id)
    return user if user is not None and user.is_active else None


def revoke_token(db: Session, raw_token: str) -> None:
    db.execute(
        update(AuthToken).where(AuthToken.token_hash == security.hash_token(raw_token)).values(revoked=True)
    )
    db.commit()


def revoke_all_tokens(db: Session, user_id: str) -> None:
    db.execute(update(AuthToken).where(AuthToken.user_id == user_id).values(revoked=True))
    db.commit()
