"""Dashboard preferences stored on the server (they follow the user across devices)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.deps import AdminAuth, Db
from app.errors import ApiError
from app.models import UserPreference
from app.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/preferences", tags=["preferences"])

KEY_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"
MAX_VALUE_BYTES = 16 * 1024
MAX_KEYS = 100

_AUTH: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}
Key = Annotated[str, Path(pattern=KEY_PATTERN, description="Preference name, e.g. report-sections")]


class PreferenceBody(BaseModel):
    value: Any


class PreferenceOut(BaseModel):
    key: str
    value: Any | None
    updated_at: datetime | None


@router.get(
    "/{key}",
    response_model=PreferenceOut,
    summary="Read a preference (null if unset)",
    responses=_AUTH,
)
async def get_preference(key: Key, _: AdminAuth, session: Db) -> PreferenceOut:
    row = (
        await session.execute(select(UserPreference).where(UserPreference.key == key))
    ).scalar_one_or_none()
    return PreferenceOut(
        key=key,
        value=None if row is None else row.value,
        updated_at=None if row is None else row.updated_at,
    )


@router.put(
    "/{key}",
    response_model=PreferenceOut,
    summary="Save a preference (any JSON value up to 16 KiB; replaces the previous one)",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def put_preference(
    key: Key, body: PreferenceBody, _: AdminAuth, session: Db
) -> PreferenceOut:
    if len(json.dumps(body.value, separators=(",", ":")).encode()) > MAX_VALUE_BYTES:
        raise ApiError(
            422, "value_too_large", f"A preference holds at most {MAX_VALUE_BYTES} bytes"
        )
    exists = (
        await session.execute(select(UserPreference.key).where(UserPreference.key == key))
    ).scalar_one_or_none()
    if exists is None:
        total = (await session.execute(select(func.count()).select_from(UserPreference))).scalar()
        if (total or 0) >= MAX_KEYS:
            raise ApiError(422, "too_many_preferences", f"At most {MAX_KEYS} preferences")
    stmt = pg_insert(UserPreference).values(key=key, value=body.value)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"], set_={"value": stmt.excluded.value, "updated_at": func.now()}
    )
    await session.execute(stmt)
    await session.commit()
    row = (
        await session.execute(select(UserPreference).where(UserPreference.key == key))
    ).scalar_one()
    return PreferenceOut(key=key, value=row.value, updated_at=row.updated_at)


@router.delete(
    "/{key}", status_code=204, summary="Forget a preference (back to the defaults)", responses=_AUTH
)
async def delete_preference(key: Key, _: AdminAuth, session: Db) -> None:
    await session.execute(delete(UserPreference).where(UserPreference.key == key))
    await session.commit()
