"""Manual exclusion of single measures: list the candidates, exclude, list the excluded, restore."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.dash_schemas import (
    ExcludeBody,
    ExcludeResult,
    ExclusionsResponse,
    MeasuresResponse,
)
from app.deps import AdminAuth, Db, SettingsDep
from app.schemas import ErrorResponse
from app.services import exclusions

router = APIRouter(prefix="/api/v1", tags=["exclusions"])
_AUTH: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


@router.get(
    "/measures",
    response_model=MeasuresResponse,
    response_model_by_alias=True,
    summary="Individual measures of a period (what a chart point aggregates), excludable ones only",
    responses={**_AUTH, 422: {"model": ErrorResponse}},
)
async def list_measures(
    _: AdminAuth,
    session: Db,
    settings: SettingsDep,
    type_: Annotated[str, Query(alias="type")],
    from_: Annotated[date, Query(alias="from")],
    to: date,
) -> MeasuresResponse:
    items = await exclusions.list_measures(session, settings, type_, from_, to)
    return MeasuresResponse(type=type_, from_=from_, to=to, measures=items)


@router.post(
    "/exclusions",
    response_model=ExcludeResult,
    status_code=201,
    summary="Exclude one measure (and its copies from other apps) from every analysis",
    responses={**_AUTH, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def exclude_measure(
    body: ExcludeBody, _: AdminAuth, session: Db, settings: SettingsDep
) -> ExcludeResult:
    result = await exclusions.exclude(session, settings, body.record_id, body.reason)
    await session.commit()
    return result


@router.get(
    "/exclusions",
    response_model=ExclusionsResponse,
    summary="Excluded measures, newest exclusion first",
    responses=_AUTH,
)
async def list_exclusions(_: AdminAuth, session: Db, settings: SettingsDep) -> ExclusionsResponse:
    return ExclusionsResponse(items=await exclusions.list_exclusions(session, settings))


@router.delete(
    "/exclusions/{group_id}",
    status_code=204,
    summary="Restore an excluded measure (the data was never deleted)",
    responses={**_AUTH, 404: {"model": ErrorResponse}},
)
async def restore_exclusion(
    group_id: uuid.UUID, _: AdminAuth, session: Db, settings: SettingsDep
) -> None:
    await exclusions.restore(session, settings, group_id)
    await session.commit()
