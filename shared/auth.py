import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.models import RefreshToken, User


class AuthError(Exception):
    pass


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_expire_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(session: Session, user_id: str) -> str:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_value(raw_token)
    expires_at = datetime.utcnow() + timedelta(seconds=settings.refresh_token_expire_seconds)
    refresh = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(refresh)
    session.commit()
    return raw_token


def rotate_refresh_token(session: Session, raw_token: str) -> Optional[tuple[str, str]]:
    token_hash = _hash_value(raw_token)
    refresh = (
        session.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .first()
    )
    if not refresh:
        return None
    if refresh.expires_at < datetime.utcnow():
        return None
    refresh.revoked_at = datetime.utcnow()
    session.add(refresh)
    session.commit()
    new_token = create_refresh_token(session, str(refresh.user_id))
    return new_token, str(refresh.user_id)


def revoke_refresh_token(session: Session, raw_token: str) -> bool:
    token_hash = _hash_value(raw_token)
    refresh = session.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if not refresh or refresh.revoked_at:
        return False
    refresh.revoked_at = datetime.utcnow()
    session.add(refresh)
    session.commit()
    return True


def decode_access_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("invalid token") from exc
    if payload.get("type") != "access":
        raise AuthError("invalid token")
    return payload.get("sub")


def get_user(session: Session, user_id: str) -> Optional[User]:
    return session.query(User).filter(User.id == user_id).first()
