"""Home Assistant alarm: token scopes, ok/stale/never, the 6 h boundary, devices, rate limit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import Settings
from app.models import Device, SyncRun
from app.services import alarm

URL = "/api/v1/ha/status"
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def bearer(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def add_run(app, device: uuid.UUID, finished: datetime, status: str = "completed") -> None:  # type: ignore[no-untyped-def]
    async with app.state.sessionmaker() as s:
        if await s.get(Device, device) is None:
            s.add(
                Device(id=device, name=f"d-{device.hex[:4]}", first_seen_at=NOW, last_seen_at=NOW)
            )
            await s.flush()
        s.add(
            SyncRun(
                id=uuid.uuid4(),
                device_id=device,
                started_at=finished - timedelta(minutes=1),
                finished_at=finished,
                last_activity_at=finished,
                status=status,
            )
        )
        await s.commit()


async def test_token_scopes_are_separate_both_ways(
    client: httpx.AsyncClient, ha_token: str, token: str
) -> None:
    assert (await client.get(URL, headers=bearer(ha_token))).status_code == 200
    r = await client.get(URL, headers=bearer(token))  # an ingest token cannot read the status
    assert r.status_code == 403 and r.json()["error"]["code"] == "wrong_token_scope"
    r = await client.post(  # a HA token cannot ingest
        "/api/v1/ingest/records",
        json={"device_id": str(uuid.uuid4()), "sync_id": str(uuid.uuid4()), "records": []},
        headers=bearer(ha_token),
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "wrong_token_scope"
    r = await client.get("/api/v1/ping", headers=bearer(ha_token))  # nor the Reader's ping
    assert r.status_code == 403 and r.json()["error"]["code"] == "wrong_token_scope"
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(URL, headers=bearer("sbh_nope"))).status_code == 401


async def test_never_without_a_successful_sync(
    client: httpx.AsyncClient,
    ha_token: str,
    app,  # type: ignore[no-untyped-def]
) -> None:
    body = (await client.get(URL, headers=bearer(ha_token))).json()
    assert body["status"] == "never"
    assert body["last_sync_at"] is None and body["hours_since_sync"] is None
    assert body["threshold_hours"] == 6.0
    await add_run(app, uuid.uuid4(), datetime.now(UTC), status="failed")  # not a success
    body = (await client.get(URL, headers=bearer(ha_token))).json()
    assert body["status"] == "never" and body["last_ingest_at"] is not None


async def test_ok_and_response_shape(
    client: httpx.AsyncClient,
    ha_token: str,
    app,  # type: ignore[no-untyped-def]
) -> None:
    await add_run(app, uuid.uuid4(), datetime.now(UTC) - timedelta(hours=1))
    body = (await client.get(URL, headers=bearer(ha_token))).json()
    assert body["status"] == "ok"
    assert set(body) == {
        "status",
        "last_sync_at",
        "last_ingest_at",
        "hours_since_sync",
        "threshold_hours",
        "version",
    }
    assert 0.9 < body["hours_since_sync"] < 1.1
    assert body["version"] == "0.8.1"


async def test_stale_when_over_threshold(
    client: httpx.AsyncClient,
    ha_token: str,
    app,  # type: ignore[no-untyped-def]
) -> None:
    await add_run(app, uuid.uuid4(), datetime.now(UTC) - timedelta(hours=7))
    body = (await client.get(URL, headers=bearer(ha_token))).json()
    assert body["status"] == "stale" and body["hours_since_sync"] > 6


def test_boundary_exactly_threshold_is_ok() -> None:
    last = NOW - timedelta(hours=6)
    assert alarm.evaluate(last, 6.0, NOW) == ("ok", 6.0)
    assert alarm.evaluate(last - timedelta(seconds=1), 6.0, NOW)[0] == "stale"
    assert alarm.evaluate(last + timedelta(seconds=1), 6.0, NOW)[0] == "ok"
    assert alarm.evaluate(None, 6.0, NOW) == ("never", None)


async def test_state_at_exact_boundary(app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    await add_run(app, uuid.uuid4(), NOW - timedelta(hours=6))
    async with app.state.sessionmaker() as s:
        assert (await alarm.alarm_state(s, settings, NOW))["status"] == "ok"
        later = NOW + timedelta(seconds=1)
        assert (await alarm.alarm_state(s, settings, later))["status"] == "stale"


async def test_any_device_counts(app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    old, fresh = uuid.uuid4(), uuid.uuid4()
    await add_run(app, old, NOW - timedelta(hours=20))
    async with app.state.sessionmaker() as s:
        assert (await alarm.alarm_state(s, settings, NOW))["status"] == "stale"
    await add_run(app, fresh, NOW - timedelta(hours=2))
    async with app.state.sessionmaker() as s:
        state = await alarm.alarm_state(s, settings, NOW)
        per_device = await alarm.last_success_per_device(s)
    assert state["status"] == "ok"
    assert per_device[old] == NOW - timedelta(hours=20)
    assert per_device[fresh] == NOW - timedelta(hours=2)


async def test_threshold_comes_from_settings(app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    await add_run(app, uuid.uuid4(), NOW - timedelta(hours=3))
    tight = settings.model_copy(update={"stale_hours": 2.0})
    async with app.state.sessionmaker() as s:
        assert (await alarm.alarm_state(s, tight, NOW))["status"] == "stale"
        assert (await alarm.alarm_state(s, settings, NOW))["status"] == "ok"


async def test_rate_limit(
    client: httpx.AsyncClient,
    ha_token: str,
    app,  # type: ignore[no-untyped-def]
) -> None:
    app.state.ha_limiter.max_requests = 3
    for _ in range(3):
        assert (await client.get(URL, headers=bearer(ha_token))).status_code == 200
    r = await client.get(URL, headers=bearer(ha_token))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


async def test_dashboard_sync_status_has_alarm_and_per_device(
    web: httpx.AsyncClient,
    app,  # type: ignore[no-untyped-def]
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await add_run(app, a, datetime.now(UTC) - timedelta(hours=20))
    await add_run(app, b, datetime.now(UTC) - timedelta(hours=2))
    body = (await web.get("/api/v1/sync/status")).json()
    assert body["alarm"]["status"] == "ok" and body["alarm"]["threshold_hours"] == 6.0
    by_id = {d["id"]: d for d in body["devices"]}
    assert by_id[str(a)]["last_success_at"] != by_id[str(b)]["last_success_at"]
    assert all(d["last_success_at"] for d in body["devices"])


@pytest.mark.parametrize("scope", ["ingest", "ha"])
async def test_admin_creates_tokens_with_scope(web: httpx.AsyncClient, scope: str) -> None:
    r = await web.post(
        "/api/v1/admin/tokens", json={"name": "x", "scope": scope}, headers={"X-SBH-Client": "web"}
    )
    assert r.status_code in (200, 201)
    listed = (await web.get("/api/v1/admin/tokens")).json()
    assert any(t["scope"] == scope for t in listed)
