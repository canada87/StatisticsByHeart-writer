"""Read-only status for Home Assistant (a dedicated, read-only token; HA polls this)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import Db, HaAuth, SettingsDep
from app.schemas import ErrorResponse
from app.services import alarm
from app.version import VERSION

router = APIRouter(prefix="/api/v1/ha", tags=["home-assistant"])


class HaStatus(BaseModel):
    status: Literal["ok", "stale", "never"] = Field(
        description="ok = a successful sync within the threshold; stale = later; never = none yet"
    )
    last_sync_at: datetime | None = Field(description="Last SUCCESSFUL sync of any device (UTC)")
    last_ingest_at: datetime | None = Field(
        description="Last time the phone sent anything (even a sync still running or failed)"
    )
    hours_since_sync: float | None
    threshold_hours: float
    version: str


@router.get(
    "/status",
    response_model=HaStatus,
    summary="Sync alarm for Home Assistant: ok / stale / never (no health values)",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def ha_status(_: HaAuth, session: Db, settings: SettingsDep) -> dict[str, Any]:
    return {**await alarm.alarm_state(session, settings), "version": VERSION}
