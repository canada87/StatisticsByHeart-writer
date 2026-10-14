from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.deps import IngestAuth, SettingsDep
from app.schemas import (
    API_VERSION,
    ErrorResponse,
    HealthResult,
    PingLimits,
    PingResult,
    PingToken,
)

router = APIRouter(prefix="/api/v1", tags=["public"])


@router.get("/health", response_model=HealthResult, summary="Liveness (no auth)")
async def health() -> HealthResult:
    return HealthResult()


@router.get(
    "/ping",
    response_model=PingResult,
    summary="Check connectivity and ingest token",
    responses={401: {"model": ErrorResponse}},
)
async def ping(token: IngestAuth, settings: SettingsDep) -> PingResult:
    return PingResult(
        api_version=API_VERSION,
        server_time=datetime.now(UTC),
        token=PingToken(name=token.name, prefix=token.token_prefix),
        limits=PingLimits(
            max_batch_records=settings.max_batch_records, max_body_bytes=settings.max_body_bytes
        ),
    )
