"""FastAPI dependencies: ingest-token auth and admin-session auth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import db_session
from app.errors import ApiError
from app.models import AdminUser, IngestToken, UserSession
from app.security import hash_token

LAST_USED_THROTTLE = timedelta(seconds=60)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-sbh-client"

Db = Annotated[AsyncSession, Depends(db_session)]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


async def require_ingest_token(request: Request, session: Db) -> IngestToken:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise ApiError(
            401, "invalid_token", "Missing bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    token = (
        await session.execute(
            select(IngestToken).where(IngestToken.token_hash == hash_token(value.strip()))
        )
    ).scalar_one_or_none()
    if token is None:
        raise ApiError(
            401, "invalid_token", "Unknown token", headers={"WWW-Authenticate": "Bearer"}
        )
    if token.revoked_at is not None:
        raise ApiError(
            401, "token_revoked", "Token has been revoked", headers={"WWW-Authenticate": "Bearer"}
        )
    now = datetime.now(UTC)
    if token.last_used_at is None or now - token.last_used_at > LAST_USED_THROTTLE:
        await session.execute(
            update(IngestToken).where(IngestToken.id == token.id).values(last_used_at=now)
        )
        await session.commit()
    return token


@dataclass
class AdminContext:
    user: AdminUser
    session: UserSession


async def require_admin(request: Request, session: Db, settings: SettingsDep) -> AdminContext:
    secret = request.cookies.get(settings.cookie_name)
    if not secret:
        raise ApiError(401, "not_authenticated", "Login required")
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(UserSession, AdminUser)
            .join(AdminUser, AdminUser.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(secret))
        )
    ).one_or_none()
    if row is None or row[0].revoked_at is not None or row[0].expires_at <= now:
        raise ApiError(401, "not_authenticated", "Session expired or invalid")
    if request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
        # Cross-site forms cannot set custom headers without a CORS preflight (which we never allow).
        raise ApiError(403, "csrf", f"Missing {CSRF_HEADER} header")
    user_session, user = row
    if now - user_session.last_seen_at > LAST_USED_THROTTLE:
        await session.execute(
            update(UserSession).where(UserSession.id == user_session.id).values(last_seen_at=now)
        )
        await session.commit()
    return AdminContext(user=user, session=user_session)


IngestAuth = Annotated[IngestToken, Depends(require_ingest_token)]
AdminAuth = Annotated[AdminContext, Depends(require_admin)]
