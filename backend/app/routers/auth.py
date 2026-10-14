from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update

from app.deps import AdminAuth, Db, SettingsDep
from app.errors import ApiError
from app.models import AdminUser, UserSession
from app.schemas import ErrorResponse, LoginRequest, SessionInfo
from app.security import hash_password, needs_rehash, new_session_secret, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    # Behind NPM the real address arrives in X-Forwarded-For; uvicorn applies it when
    # --forwarded-allow-ips matches the proxy. Used only for rate limiting and audit.
    return request.client.host if request.client else "unknown"


@router.post(
    "/login",
    response_model=SessionInfo,
    summary="Admin login (sets an HttpOnly session cookie)",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Db,
    settings: SettingsDep,
) -> SessionInfo:
    limiter = request.app.state.login_limiter
    keys = (f"ip:{_client_ip(request)}", f"user:{body.username.lower()}")
    wait = limiter.retry_after(*keys)
    if wait:
        raise ApiError(
            429,
            "too_many_attempts",
            "Too many failed logins, try again later",
            headers={"Retry-After": str(wait)},
        )

    user = (
        await session.execute(select(AdminUser).where(AdminUser.username == body.username))
    ).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        limiter.fail(*keys)
        raise ApiError(401, "invalid_credentials", "Wrong username or password")
    limiter.reset(*keys)

    if needs_rehash(user.password_hash):
        await session.execute(
            update(AdminUser)
            .where(AdminUser.id == user.id)
            .values(password_hash=hash_password(body.password))
        )

    now = datetime.now(UTC)
    secret, secret_hash = new_session_secret()
    expires = now + timedelta(hours=settings.session_ttl_hours)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=secret_hash,
            expires_at=expires,
            ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    )
    await session.commit()
    response.set_cookie(
        settings.cookie_name,
        secret,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return SessionInfo(username=user.username, expires_at=expires)


@router.post("/logout", status_code=204, summary="Revoke the current session")
async def logout(auth: AdminAuth, response: Response, session: Db, settings: SettingsDep) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.id == auth.session.id)
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    response.delete_cookie(settings.cookie_name, path="/")


@router.get(
    "/me",
    response_model=SessionInfo,
    summary="Current session",
    responses={401: {"model": ErrorResponse}},
)
async def me(auth: AdminAuth) -> SessionInfo:
    return SessionInfo(username=auth.user.username, expires_at=auth.session.expires_at)
