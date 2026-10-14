from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select, update

from app.deps import AdminAuth, Db
from app.errors import ApiError
from app.models import IngestToken, SyncRun
from app.schemas import ErrorResponse, SyncRunInfo, TokenCreate, TokenCreated, TokenInfo
from app.security import new_ingest_token

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
_AUTH: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


def _info(t: IngestToken) -> dict[str, object]:
    return {
        "id": t.id,
        "name": t.name,
        "prefix": t.token_prefix,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "revoked_at": t.revoked_at,
    }


@router.post(
    "/tokens",
    response_model=TokenCreated,
    status_code=201,
    summary="Create an ingest token (plaintext shown once)",
    responses=_AUTH,
)
async def create_token(body: TokenCreate, _: AdminAuth, session: Db) -> TokenCreated:
    plaintext, token_hash, prefix = new_ingest_token()
    token = IngestToken(id=uuid.uuid4(), name=body.name, token_hash=token_hash, token_prefix=prefix)
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return TokenCreated(**_info(token), token=plaintext)


@router.get(
    "/tokens", response_model=list[TokenInfo], summary="List ingest tokens", responses=_AUTH
)
async def list_tokens(_: AdminAuth, session: Db) -> list[TokenInfo]:
    rows = (await session.execute(select(IngestToken).order_by(IngestToken.created_at))).scalars()
    return [TokenInfo(**_info(t)) for t in rows]


@router.delete(
    "/tokens/{token_id}",
    status_code=204,
    summary="Revoke an ingest token (idempotent)",
    responses={**_AUTH, 404: {"model": ErrorResponse}},
)
async def revoke_token(token_id: uuid.UUID, _: AdminAuth, session: Db) -> None:
    token = await session.get(IngestToken, token_id)
    if token is None:
        raise ApiError(404, "not_found", "No such token")
    if token.revoked_at is None:
        await session.execute(
            update(IngestToken)
            .where(IngestToken.id == token_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()


@router.get(
    "/sync-runs",
    response_model=list[SyncRunInfo],
    summary="Recent sync runs (server-side counters vs Reader report)",
    responses=_AUTH,
)
async def list_sync_runs(
    _: AdminAuth, session: Db, limit: int = Query(50, ge=1, le=200)
) -> list[SyncRunInfo]:
    rows = (
        await session.execute(
            select(SyncRun).order_by(SyncRun.last_activity_at.desc()).limit(limit)
        )
    ).scalars()
    return [
        SyncRunInfo(
            sync_id=r.id,
            device_id=r.device_id,
            mode=r.mode,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            last_activity_at=r.last_activity_at,
            server_counts={
                "records_received": r.records_received,
                "records_inserted": r.records_inserted,
                "records_updated": r.records_updated,
                "records_unchanged": r.records_unchanged,
                "records_rejected": r.records_rejected,
                "deletions_applied": r.deletions_applied,
                "deletions_not_found": r.deletions_not_found,
                "aggregates_upserted": r.aggregates_upserted,
            },
            reported_counts=r.reported_counts,
            errors=r.errors,
        )
        for r in rows
    ]
