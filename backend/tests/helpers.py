"""Payload builders and DB probes shared by the tests."""

from __future__ import annotations

import gzip
import json
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text

DEVICE = "5b0c3c0e-6a7e-4a38-9f0e-0a9d3b1c2d4e"
SYNC = "0f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a10"
LM = "2026-10-14T20:00:00Z"


def record(
    type_: str,
    hc_id: str,
    start: str,
    end: str | None,
    data: dict[str, Any],
    *,
    pkg: str = "pkg.a",
    offset: int | None = 7200,
    last_modified: str = LM,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "type": type_,
        "hc_id": hc_id,
        "start_time": start,
        "source": {"package": pkg},
        "last_modified": last_modified,
        "data": data,
    }
    if end is not None:
        rec["end_time"] = end
    if offset is not None:
        rec["start_offset_s"] = offset
        if end is not None:
            rec["end_offset_s"] = offset
    return rec


def steps(hc_id: str, start: str, end: str, n: float, **kw: Any) -> dict[str, Any]:
    return record("Steps", hc_id, start, end, {"value": n}, **kw)


def records_body(records: list[Any], sync_id: str = SYNC) -> dict[str, Any]:
    return {"device_id": DEVICE, "sync_id": sync_id, "records": records}


async def post(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    path: str,
    body: dict[str, Any],
    *,
    gz: bool = False,
) -> httpx.Response:
    if gz:
        return await client.post(
            f"/api/v1/ingest/{path}",
            content=gzip.compress(json.dumps(body).encode()),
            headers={**auth, "Content-Type": "application/json", "Content-Encoding": "gzip"},
        )
    return await client.post(f"/api/v1/ingest/{path}", json=body, headers=auth)


async def post_records(
    client: httpx.AsyncClient, auth: dict[str, str], records: list[Any], **kw: Any
) -> dict[str, Any]:
    r = await post(client, auth, "records", records_body(records), **kw)
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    return result


async def rows(app: FastAPI, sql: str, **params: Any) -> list[Any]:
    async with app.state.sessionmaker() as s:
        return list((await s.execute(text(sql), params)).all())


async def scalar(app: FastAPI, sql: str, **params: Any) -> Any:
    async with app.state.sessionmaker() as s:
        return (await s.execute(text(sql), params)).scalar()


async def computed(app: FastAPI, type_: str, day: str, source: str = "computed") -> Any:
    found = await rows(
        app,
        "SELECT sum_value, avg_value, min_value, max_value, count, detail FROM daily_metric "
        "WHERE type=:t AND local_date=:d AND source=:s",
        t=type_,
        d=day,
        s=source,
    )
    return found[0] if found else None
