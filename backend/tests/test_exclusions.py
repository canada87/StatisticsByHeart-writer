"""Manual exclusion of single measures (ADR 0011)."""

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.services import heartpoints
from app.services.exclusions import Rec, cluster, is_twin
from tests.conftest import TODAY
from tests.helpers import DEVICE, SYNC, computed, post, post_records, record, rows, scalar

W = {"X-SBH-Client": "web"}
D1, D2, D3 = "2026-10-12", "2026-10-13", "2026-10-14"


def weight(
    hc_id: str,
    day: str,
    kg: float,
    *,
    pkg: str = "scale",
    hour: str = "07:10",
    lm: str = "2026-10-15T08:00:00Z",
):
    return record(
        "Weight", hc_id, f"{day}T{hour}:00+02:00", None, {"value": kg}, pkg=pkg, last_modified=lm
    )


async def _measures(web: httpx.AsyncClient, type_: str, first: str, last: str) -> list[dict]:
    r = await web.get(f"/api/v1/measures?type={type_}&from={first}&to={last}")
    assert r.status_code == 200, r.text
    return r.json()["measures"]


async def _exclude(web: httpx.AsyncClient, record_id: int, reason: str | None = None) -> dict:
    r = await web.post(
        "/api/v1/exclusions", json={"record_id": record_id, "reason": reason}, headers=W
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _series_values(
    web: httpx.AsyncClient, type_: str, first: str, last: str, **q: str
) -> dict[str, float | None]:
    extra = "".join(f"&{k}={v}" for k, v in q.items())
    body = (
        await web.get(f"/api/v1/metrics/{type_}/series?from={first}&to={last}&bucket=day{extra}")
    ).json()
    return {p["t"]: p["v"] for p in body["points"]}


# --------------------------------------------------------------------------- pure rules


def _rec(i: int, start: str, end: str | None, type_: str = "Weight") -> Rec:
    s = datetime.fromisoformat(start)
    return Rec(
        i, f"h{i}", type_, s, datetime.fromisoformat(end) if end else None, s.date(), "pkg", {}
    )


def test_instants_are_copies_only_at_the_same_instant() -> None:
    a, b, c = (
        _rec(1, "2026-10-12T07:10:00+02:00", None),
        _rec(2, "2026-10-12T07:10:00+02:00", None),
        _rec(3, "2026-10-12T07:11:00+02:00", None),
    )
    assert is_twin(a, b) and not is_twin(a, c)
    assert [len(g) for g in cluster([a, b, c])] == [2, 1]


def test_sessions_are_copies_when_they_overlap_by_more_than_half() -> None:
    a = _rec(1, "2026-10-12T23:00:00+02:00", "2026-10-13T07:00:00+02:00", "SleepSession")
    b = _rec(2, "2026-10-12T23:10:00+02:00", "2026-10-13T06:50:00+02:00", "SleepSession")
    nap = _rec(3, "2026-10-13T14:00:00+02:00", "2026-10-13T14:30:00+02:00", "SleepSession")
    assert is_twin(a, b) and not is_twin(a, nap)
    assert [len(g) for g in cluster([nap, b, a])] == [2, 1]


# --------------------------------------------------------------------------- the main scenario


async def test_excluded_weight_disappears_everywhere_and_comes_back(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client, auth, [weight("w1", D1, 78.0), weight("w2", D2, 32.0), weight("w3", D3, 78.4)]
    )
    assert (await computed(app, "Weight", D2))[0] is None  # no sum for instants; avg is column 1
    assert (await computed(app, "Weight", D2))[1] == 32.0
    before = await _series_values(web, "Weight", D1, D3)
    assert before[D2] == 32.0

    measures = await _measures(web, "Weight", D1, D3)
    assert [m["value"] for m in measures] == [78.4, 32.0, 78.0]  # newest first
    foreign = measures[1]
    result = await _exclude(web, foreign["ids"][0], "figlio, altro profilo")
    assert result["records"] == 1 and result["days"] == 1 and result["measure"]["value"] == 32.0

    # gone from the daily rows, the series, the KPIs and the report
    assert await computed(app, "Weight", D2) is None
    assert (await _series_values(web, "Weight", D1, D3))[D2] is None
    s = (
        await web.get(
            f"/api/v1/metrics/Weight/series?from={D1}&to={D3}&bucket=day&compare=true&ma=true&band=true"
        )
    ).json()
    assert s["summary"]["min"] == 78.0 and s["summary"]["points"] == 2
    report = (await web.get(f"/api/v1/report?from={D1}&to={D3}")).json()
    wm = next(m for m in report["metrics"] if m["key"] == "weight")
    assert wm["days_with_data"] == 2 and wm["current"]["min"] == 78.0
    daily = (await web.get(f"/api/v1/report/daily?from={D1}&to={D3}")).json()
    by_day = {r["date"]: r["values"]["weight_kg"] for r in daily["rows"]}
    assert D2 not in by_day or by_day[D2] is None
    assert [m["value"] for m in await _measures(web, "Weight", D1, D3)] == [78.4, 78.0]

    # the data is still there
    assert await scalar(app, "SELECT count(*) FROM health_record WHERE type='Weight'") == 3
    assert (
        await scalar(app, "SELECT deleted_at IS NULL FROM health_record WHERE hc_id='w2'") is True
    )

    listing = (await web.get("/api/v1/exclusions")).json()["items"]
    assert len(listing) == 1
    item = listing[0]
    assert (item["type"], item["value"], item["unit"], item["reason"], item["state"]) == (
        "Weight",
        32.0,
        "kg",
        "figlio, altro profilo",
        "present",
    )
    assert item["local_date"] == D2 and item["sources"] == ["scale"] and item["created_at"]

    # restore: the value is back, everywhere
    assert (
        await web.delete(f"/api/v1/exclusions/{item['group_id']}", headers=W)
    ).status_code == 204
    assert (await _series_values(web, "Weight", D1, D3))[D2] == 32.0
    assert (await computed(app, "Weight", D2))[1] == 32.0
    assert (await web.get("/api/v1/exclusions")).json()["items"] == []


async def test_copies_from_other_apps_are_excluded_together(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    # the scale app and Google Fit both report the 32 kg at the same instant
    await post_records(
        client,
        auth,
        [
            weight("a", D1, 78.0),
            weight("fit", D2, 32.0, pkg="fit"),
            weight("scale", D2, 32.0, pkg="scale"),
        ],
    )
    measures = await _measures(web, "Weight", D2, D2)
    assert (
        len(measures) == 1
        and len(measures[0]["ids"]) == 2
        and measures[0]["sources"] == ["fit", "scale"]
    )
    result = await _exclude(web, measures[0]["ids"][0])
    assert result["records"] == 2
    assert await scalar(app, "SELECT count(*) FROM record_exclusion") == 2
    assert await computed(app, "Weight", D2) is None  # the surviving twin does not take its place
    items = (await web.get("/api/v1/exclusions")).json()["items"]
    assert len(items) == 1 and items[0]["sources"] == ["fit", "scale"]
    assert (
        await web.delete(f"/api/v1/exclusions/{items[0]['group_id']}", headers=W)
    ).status_code == 204
    assert await scalar(app, "SELECT count(*) FROM record_exclusion") == 0
    assert (await computed(app, "Weight", D2))[1] == 32.0


async def test_exclusion_survives_reingest_and_updates(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [weight("w1", D1, 78.0), weight("w2", D2, 32.0)])
    await _exclude(web, (await _measures(web, "Weight", D2, D2))[0]["ids"][0])
    stored = await rows(app, "SELECT group_id, created_at FROM record_exclusion")

    # the Reader sends the same record again, then an updated version, then a backfill of everything
    r1 = await post_records(client, auth, [weight("w2", D2, 32.0)])
    assert r1["unchanged"] == 1
    r2 = await post_records(client, auth, [weight("w2", D2, 33.5, lm="2026-10-16T08:00:00Z")])
    assert r2["updated"] == 1
    await post_records(
        client, auth, [weight("w1", D1, 78.0), weight("w2", D2, 33.5, lm="2026-10-16T08:00:00Z")]
    )

    assert await computed(app, "Weight", D2) is None
    assert (await _series_values(web, "Weight", D1, D2))[D2] is None
    assert await _measures(web, "Weight", D2, D2) == []
    assert await rows(app, "SELECT group_id, created_at FROM record_exclusion") == stored
    # the update is kept in the record itself (the exclusions page shows the new value)
    item = (await web.get("/api/v1/exclusions")).json()["items"][0]
    assert item["value"] == 33.5
    # restoring shows the CURRENT value, not the one at exclusion time
    await web.delete(f"/api/v1/exclusions/{item['group_id']}", headers=W)
    assert (await _series_values(web, "Weight", D1, D2))[D2] == 33.5


async def test_deletion_in_health_connect_is_not_an_error(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [weight("w1", D1, 78.0), weight("w2", D2, 32.0)])
    await _exclude(web, (await _measures(web, "Weight", D2, D2))[0]["ids"][0])

    r = await post(
        client,
        auth,
        "deletions",
        {"device_id": DEVICE, "sync_id": SYNC, "items": [{"hc_id": "w2"}]},
    )
    assert r.status_code == 200 and r.json()["deleted"] == 1
    items = (await web.get("/api/v1/exclusions")).json()["items"]
    assert len(items) == 1 and items[0]["state"] == "deleted_in_hc"

    # even if the stored row is gone altogether the exclusion is listed and can be removed
    await app.state.engine.dispose()
    async with app.state.sessionmaker() as s:
        from sqlalchemy import text

        await s.execute(text("DELETE FROM health_record WHERE hc_id='w2'"))
        await s.commit()
    items = (await web.get("/api/v1/exclusions")).json()["items"]
    assert len(items) == 1 and items[0]["state"] == "missing" and items[0]["start"] is None
    assert (
        await web.delete(f"/api/v1/exclusions/{items[0]['group_id']}", headers=W)
    ).status_code == 204


# --------------------------------------------------------------------------- scope and safety


async def test_only_point_measures_and_sessions_can_be_excluded(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client,
        auth,
        [record("Steps", "s1", f"{D1}T08:00:00+02:00", f"{D1}T08:15:00+02:00", {"value": 100})],
    )
    for type_ in ("Steps", "HeartRate", "TotalCaloriesBurned", "Nope"):
        r = await web.get(f"/api/v1/measures?type={type_}&from={D1}&to={D1}")
        assert r.status_code == 422 and r.json()["error"]["code"] == "type_not_excludable"
    # a cumulative record id is refused too
    rid = await scalar(app, "SELECT id FROM health_record WHERE hc_id='s1'")
    r = await web.post("/api/v1/exclusions", json={"record_id": rid}, headers=W)
    assert r.status_code == 422 and r.json()["error"]["code"] == "type_not_excludable"
    assert (
        await web.post("/api/v1/exclusions", json={"record_id": 99999}, headers=W)
    ).status_code == 404
    bad = await web.get(f"/api/v1/measures?type=Weight&from={D3}&to={D1}")
    assert bad.status_code == 422


async def test_exclude_is_idempotent_and_restore_of_unknown_group_is_404(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [weight("w1", D1, 32.0)])
    rid = (await _measures(web, "Weight", D1, D1))[0]["ids"][0]
    first = await _exclude(web, rid, "uno")
    second = await _exclude(web, rid, "due")
    assert first["group_id"] == second["group_id"]
    assert await scalar(app, "SELECT count(*) FROM record_exclusion") == 1
    assert await scalar(app, "SELECT reason FROM record_exclusion") == "uno"
    unknown = await web.delete("/api/v1/exclusions/00000000-0000-0000-0000-000000000000", headers=W)
    assert unknown.status_code == 404


async def test_endpoints_need_an_admin_session_and_the_csrf_header(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(client, auth, [weight("w1", D1, 32.0)])
    rid = (await _measures(web, "Weight", D1, D1))[0]["ids"][0]
    no_header = await web.post("/api/v1/exclusions", json={"record_id": rid})
    assert no_header.status_code == 403 and no_header.json()["error"]["code"] == "csrf"
    assert (
        await web.delete("/api/v1/exclusions/00000000-0000-0000-0000-000000000000")
    ).status_code == 403
    # an ingest token is not a session
    async with httpx.AsyncClient(transport=client._transport, base_url="http://test") as anon:
        for method, path in (
            ("GET", "/api/v1/exclusions"),
            ("GET", f"/api/v1/measures?type=Weight&from={D1}&to={D1}"),
        ):
            assert (await anon.request(method, path, headers=auth)).status_code == 401
        assert (
            await anon.post("/api/v1/exclusions", json={"record_id": rid}, headers={**auth, **W})
        ).status_code == 401


async def test_reason_is_optional_and_trimmed(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [weight("w1", D1, 32.0)])
    rid = (await _measures(web, "Weight", D1, D1))[0]["ids"][0]
    await _exclude(web, rid, "   ")
    assert await scalar(app, "SELECT reason FROM record_exclusion") is None
    too_long = await web.post(
        "/api/v1/exclusions", json={"record_id": rid, "reason": "x" * 201}, headers=W
    )
    assert too_long.status_code == 422


# --------------------------------------------------------------------------- only the touched days


async def test_only_the_days_touched_are_recomputed(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client, auth, [weight("w1", D1, 78.0), weight("w2", D2, 32.0), weight("w3", D3, 78.4)]
    )
    stamps = {
        str(d): u
        for d, u in await rows(
            app, "SELECT local_date, updated_at FROM daily_metric WHERE type='Weight'"
        )
    }
    result = await _exclude(web, (await _measures(web, "Weight", D2, D2))[0]["ids"][0])
    assert result["days"] == 1
    after = {
        str(d): u
        for d, u in await rows(
            app, "SELECT local_date, updated_at FROM daily_metric WHERE type='Weight'"
        )
    }
    assert set(after) == {D1, D3}
    assert after[D1] == stamps[D1] and after[D3] == stamps[D3]


async def test_a_period_lists_the_single_measures_not_an_aggregate(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [
            weight("a", D1, 78.0),
            weight("b", D1, 77.0, hour="21:00"),
            weight("c", D2, 78.4),
            weight("d", D3, 32.0),
        ],
    )
    week = await _measures(web, "Weight", D1, D3)
    assert [m["value"] for m in week] == [32.0, 78.4, 77.0, 78.0]  # two on D1: both listed
    assert all(m["unit"] == "kg" and m["local_date"] and len(m["ids"]) == 1 for m in week)


# --------------------------------------------------------------------------- the other types


async def test_blood_pressure_and_spo2_and_resting_hr_and_hrv(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client,
        auth,
        [
            record(
                "BloodPressure",
                "bp1",
                f"{D1}T08:00:00+02:00",
                None,
                {"systolic": 118, "diastolic": 76},
            ),
            record(
                "BloodPressure",
                "bp2",
                f"{D2}T08:00:00+02:00",
                None,
                {"systolic": 190, "diastolic": 120},
            ),
            record("OxygenSaturation", "o1", f"{D1}T03:00:00+02:00", None, {"value": 96}),
            record("OxygenSaturation", "o2", f"{D2}T03:00:00+02:00", None, {"value": 71}),
            record("RestingHeartRate", "r1", f"{D1}T07:00:00+02:00", None, {"value": 55}),
            record("RestingHeartRate", "r2", f"{D2}T07:00:00+02:00", None, {"value": 120}),
            record("HeartRateVariabilityRmssd", "h1", f"{D1}T03:00:00+02:00", None, {"value": 45}),
            record("HeartRateVariabilityRmssd", "h2", f"{D2}T03:00:00+02:00", None, {"value": 5}),
        ],
    )
    bp = (await _measures(web, "BloodPressure", D2, D2))[0]
    assert (bp["value"], bp["value2"], bp["unit"]) == (190, 120, "mmHg")
    for type_, hc in (
        ("BloodPressure", "bp2"),
        ("OxygenSaturation", "o2"),
        ("RestingHeartRate", "r2"),
        ("HeartRateVariabilityRmssd", "h2"),
    ):
        await _exclude(web, (await _measures(web, type_, D2, D2))[0]["ids"][0])
        assert await computed(app, type_, D2) is None, hc
        assert await computed(app, type_, D1) is not None
    dia = await _series_values(web, "BloodPressure", D1, D2, field="diastolic")
    assert dia[D2] is None and dia[D1] == 76
    report = (await web.get(f"/api/v1/report?from={D1}&to={D2}")).json()
    by = {m["key"]: m for m in report["metrics"]}
    assert by["resting_hr"]["current"]["max"] == 55 and by["spo2"]["current"]["min"] == 96
    assert by["hrv"]["current"]["min"] == 45 and by["blood_pressure"]["current"]["max"] == 118


async def test_excluded_sleep_leaves_nights_series_and_the_day_night_split(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client,
        auth,
        [
            record(
                "SleepSession", "n1", "2026-10-11T23:00:00+02:00", "2026-10-12T07:00:00+02:00", {}
            ),
            record(
                "SleepSession", "n2", "2026-10-12T23:00:00+02:00", "2026-10-13T07:00:00+02:00", {}
            ),
            record(
                "SleepSession",
                "n2b",
                "2026-10-12T23:05:00+02:00",
                "2026-10-13T06:50:00+02:00",
                {},
                pkg="other",
            ),
        ],
    )
    nights = (await web.get(f"/api/v1/sleep/nights?from={D1}&to={D2}")).json()
    assert [n["date"] for n in nights["nights"]] == [D1, D2]
    day = await _measures(web, "SleepSession", D2, D2)
    assert (
        len(day) == 1 and len(day[0]["ids"]) == 2 and day[0]["unit"] == "s"
    )  # both apps, one night
    await _exclude(web, day[0]["ids"][0], "sonno del figlio")
    nights = (await web.get(f"/api/v1/sleep/nights?from={D1}&to={D2}")).json()
    assert [n["date"] for n in nights["nights"]] == [D1]
    sleep = await _series_values(web, "SleepSession", D1, D2)
    assert sleep[D2] is None and sleep[D1] == 8 * 3600
    assert await computed(app, "SleepSession", D2) is None


async def test_excluded_workout_leaves_every_workout_view_and_the_heart_points_minutes(
    seeded: None, web: httpx.AsyncClient, app: FastAPI, settings: Settings
) -> None:
    first = (TODAY - timedelta(days=9)).isoformat()
    sessions = (
        await web.get(f"/api/v1/exercise/sessions?from={first}&to={TODAY}&scope=all")
    ).json()
    assert sessions["sessions"], "the seed has workouts"
    target = sessions["sessions"][0]
    local_day = await scalar(
        app, "SELECT local_date FROM health_record WHERE id=:i", i=target["id"]
    )
    async with app.state.sessionmaker() as s:
        minutes_before = len(await heartpoints.session_minutes(s, settings, local_day))
    assert minutes_before > 0

    measures = await _measures(web, "ExerciseSession", str(local_day), str(local_day))
    assert any(target["id"] in m["ids"] for m in measures)
    result = await _exclude(web, target["id"], "allenamento di un altro")
    assert result["records"] >= 1

    after = (await web.get(f"/api/v1/exercise/sessions?from={first}&to={TODAY}&scope=all")).json()
    assert target["id"] not in {s["id"] for s in after["sessions"]}
    assert after["total_count"] == sessions["total_count"] - 1
    summary = (await web.get("/api/v1/summary/today")).json()
    assert all(a["id"] != target["id"] for a in summary["activities"])
    async with app.state.sessionmaker() as s:
        assert len(await heartpoints.session_minutes(s, settings, local_day)) < minutes_before
    # restore puts everything back
    gid = (await web.get("/api/v1/exclusions")).json()["items"][0]["group_id"]
    await web.delete(f"/api/v1/exclusions/{gid}", headers=W)
    again = (await web.get(f"/api/v1/exercise/sessions?from={first}&to={TODAY}&scope=all")).json()
    assert again["total_count"] == sessions["total_count"]


async def test_the_seed_has_a_foreign_weight_to_demo_the_feature(
    seeded: None, web: httpx.AsyncClient
) -> None:
    first = (TODAY - timedelta(days=9)).isoformat()
    weights = await _measures(web, "Weight", first, str(TODAY))
    odd = [m for m in weights if m["value"] == 32.0]
    assert len(odd) == 1 and odd[0]["sources"] == ["synthetic.phone", "synthetic.scale"]
    await _exclude(web, odd[0]["ids"][0])
    series = (
        await web.get(f"/api/v1/metrics/Weight/series?from={first}&to={TODAY}&bucket=day")
    ).json()
    assert series["summary"]["min"] > 70


@pytest.mark.parametrize(
    "path", ["/api/v1/exclusions", "/api/v1/measures?type=Weight&from=2026-10-01&to=2026-10-02"]
)
async def test_read_endpoints_are_not_public(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401
