from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.deps.db import get_db
from shared.config import get_settings
from shared.models import AuthIdentity, User


def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> str:
    if getattr(request.state, "user_id", None):
        return request.state.user_id
    external_sub: Optional[str] = getattr(request.state, "external_sub", None)
    if not external_sub:
        raise HTTPException(status_code=401, detail="missing token")
    settings = get_settings()
    identity = (
        db.query(AuthIdentity)
        .filter(AuthIdentity.provider == settings.auth_provider_name, AuthIdentity.provider_uid == external_sub)
        .first()
    )
    if identity:
        request.state.user_id = str(identity.user_id)
        return request.state.user_id

    claims = getattr(request.state, "claims", {})
    user = User(
        nickname=claims.get("name"),
        avatar_url=claims.get("picture"),
    )
    db.add(user)
    db.commit()
    identity = AuthIdentity(
        user_id=user.id,
        provider=settings.auth_provider_name,
        provider_uid=external_sub,
    )
    db.add(identity)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        identity = (
            db.query(AuthIdentity)
            .filter(AuthIdentity.provider == settings.auth_provider_name, AuthIdentity.provider_uid == external_sub)
            .first()
        )
        if not identity:
            raise HTTPException(status_code=500, detail="identity creation failed")
        request.state.user_id = str(identity.user_id)
        return request.state.user_id

    request.state.user_id = str(user.id)
    return request.state.user_id


def require_auth(user_id: str = Depends(get_current_user_id)) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="missing token")
    return user_id
