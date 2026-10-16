"""Real workouts (ADR 0006): the rule, the manual override, the day/night split and the report."""

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI

from app.services.workouts import (
    HR_COVERAGE_MIN,
    MIN_DURATION,
    NOT_REAL_TYPES,
    RECOVERY_AFTER_S,
    describe_rules,
    evaluate_rules,
)
from tests.conftest import TODAY
from tests.helpers import DEVICE, post, post_records, record

CSRF = {"X-SBH-Client": "web"}
DAY = "2026-10-14"
START = f"{DAY}T18:00:00+02:00"
END = f"{DAY}T18:30:00+02:00"


def _hr(hc: str, start: str, end: str, samples: list[tuple[str, int]]) -> dict[str, object]:
    return record(
        "HeartRate",
        hc,
        start,
        end,
        {"samples": [{"time": t, "value": v} for t, v in samples]},
    )


def _minutes(day: str, hour: int, minute: int, count: int, value: int) -> list[tuple[str, int]]:
    out = []
    for k in range(count):
        total = hour * 60 + minute + k
        out.append((f"{day}T{total // 60:02d}:{total % 60:02d}:00+02:00", value))
    return out


def _workout(
    hc: str = "w1",
    *,
    kind: str = "RUNNING",
    end: str = END,
    method: str | None = None,
    route: bool = False,
    last_modified: str = "2026-10-14T20:00:00Z",
    pkg: str = "pkg.a",
) -> dict[str, object]:
    data: dict[str, object] = {"exercise_type": kind, "title": "Run"}
    if route:
        data["route"] = [
            {"time": START, "lat": 0.0001, "lon": 0.0002},
            {"time": f"{DAY}T18:01:00+02:00", "lat": 0.0002, "lon": 0.0003},
        ]
    return record(
        "ExerciseSession", hc, START, end, data, method=method, last_modified=last_modified, pkg=pkg
    )


async def _session(web: httpx.AsyncClient, scope: str = "all") -> list[dict]:
    r = await web.get(f"/api/v1/exercise/sessions?from={DAY}&to={DAY}&scope={scope}")
    assert r.status_code == 200, r.text
    return list(r.json()["sessions"])


def test_the_thresholds_are_the_documented_ones() -> None:
    assert HR_COVERAGE_MIN == 0.5 and RECOVERY_AFTER_S == 30 * 60
    assert {"WALKING"} == NOT_REAL_TYPES  # the one place to refine the rule
    assert MIN_DURATION.total_seconds() == 15 * 60


# --------------------------------------------------------------------------- the rule


@pytest.mark.parametrize(
    ("kind", "method", "route", "dense_hr", "real"),
    [
        ("RUNNING", "active", True, True, True),
        ("RUNNING", "automatic", False, False, True),  # no GPS, no HR, not started: still real
        ("BIKING", None, False, False, True),
        ("HIKING", "automatic", True, True, True),  # a hike is a workout
        ("STRENGTH_TRAINING", "manual", False, False, True),
        ("WALKING", "active", True, True, False),  # started, GPS, heart rate: still just a walk
        ("WALKING", "automatic", True, True, False),  # Google derives GPS for detected walks
        ("WALKING", None, False, False, False),
    ],
)
async def test_the_rule_is_the_exercise_type(
    web: httpx.AsyncClient,
    client: httpx.AsyncClient,
    auth: dict[str, str],
    kind: str,
    method: str | None,
    route: bool,
    dense_hr: bool,
    real: bool,
) -> None:
    samples = _minutes(DAY, 18, 0, 30 if dense_hr else 3, 140)  # 3 samples = 10% of the minutes
    await post_records(
        client,
        auth,
        [_hr("h1", START, END, samples), _workout(kind=kind, method=method, route=route)],
    )
    (s,) = await _session(web)
    assert s["is_real"] is real and s["auto_real"] is real and s["override"] is None
    # the signals are still reported, as information only
    assert s["has_hr"] is dense_hr and s["has_route"] is route
    assert s["started_by_user"] is (method in ("active", "manual"))
    assert s["hr_coverage"] == pytest.approx(1.0 if dense_hr else 0.1, abs=0.04)
    assert len(await _session(web, "real")) == (1 if real else 0)


def test_evaluation_order_type_then_duration_then_real() -> None:
    assert evaluate_rules("WALKING", 3600) == "type"
    assert (
        evaluate_rules("WALKING", 60) == "type"
    )  # both apply: the first rule in the order is shown
    assert evaluate_rules("RUNNING", 14 * 60 + 59) == "duration"
    assert evaluate_rules("RUNNING", 15 * 60) == "ok"  # exactly the minimum is real
    assert evaluate_rules("HIKING", 15 * 60 + 1) == "ok"


@pytest.mark.parametrize(
    ("end", "rule", "real"),
    [
        (f"{DAY}T18:10:00+02:00", "duration", False),  # a 10-minute run
        (f"{DAY}T18:14:59+02:00", "duration", False),
        (f"{DAY}T18:15:00+02:00", "ok", True),  # exactly 15 minutes
        (f"{DAY}T18:30:00+02:00", "ok", True),
    ],
)
async def test_minimum_duration(
    web: httpx.AsyncClient,
    client: httpx.AsyncClient,
    auth: dict[str, str],
    end: str,
    rule: str,
    real: bool,
) -> None:
    await post_records(client, auth, [_workout(end=end, method="active")])
    (s,) = await _session(web)
    assert (s["auto_rule"], s["auto_real"], s["is_real"]) == (rule, real, real)
    assert s["min_duration_min"] == 15


async def test_a_short_walk_is_reported_as_a_walk_first(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(client, auth, [_workout(kind="WALKING", end=f"{DAY}T18:05:00+02:00")])
    (s,) = await _session(web)
    assert s["auto_rule"] == "type"  # the first rule in the order, not the duration


async def test_the_override_beats_the_minimum_duration(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(client, auth, [_workout(end=f"{DAY}T18:08:00+02:00")])
    (s,) = await _session(web)
    assert s["is_real"] is False
    r = await web.put(
        f"/api/v1/exercise/sessions/{s['id']}/override", json={"value": True}, headers=CSRF
    )
    assert r.json()["is_real"] is True
    (s,) = await _session(web)
    assert (s["auto_rule"], s["is_real"]) == ("duration", True)
    assert len(await _session(web, "real")) == 1


async def test_rules_endpoint_is_built_from_the_constants(web: httpx.AsyncClient) -> None:
    r = await web.get("/api/v1/exercise/rules")
    assert r.status_code == 200, r.text
    assert r.json() == describe_rules()
    rules = r.json()["rules"]
    assert [x["id"] for x in rules] == ["override", "type", "duration", "default"]  # the order
    assert rules[1]["params"] == {"types": sorted(NOT_REAL_TYPES)}
    assert rules[2]["params"] == {"min_minutes": 15}
    assert r.json()["daytime_hr"] == {"excludes": "real_workouts", "recovery_minutes": 30}
    assert r.json()["signals"]["informative_only"] is True


async def test_the_rules_endpoint_needs_a_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/exercise/rules")).status_code == 401


async def test_signals_of_the_duplicate_copy_are_merged_but_do_not_decide(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    """The watch has the GPS route, the phone started the session: one walk, both signals shown."""
    await post_records(
        client,
        auth,
        [
            _hr("h1", START, END, _minutes(DAY, 18, 0, 30, 140)),
            _workout("w-watch", kind="WALKING", method="automatic", route=True, pkg="pkg.watch"),
            _workout("w-phone", kind="WALKING", method="active", route=False, pkg="pkg.phone"),
        ],
    )
    sessions = await _session(web)
    assert len(sessions) == 1
    assert sessions[0]["has_route"] is True and sessions[0]["started_by_user"] is True
    assert sessions[0]["is_real"] is False


async def test_a_resent_route_does_not_change_the_verdict(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    """Reader re-sends a past walk with its GPS route and the same last_modified."""
    await post_records(client, auth, [_workout(kind="WALKING", method="automatic")])
    assert (await _session(web))[0]["is_real"] is False
    result = await post_records(
        client, auth, [_workout(kind="WALKING", method="automatic", route=True)]
    )
    assert result["updated"] == 1  # the data changed ...
    (s,) = await _session(web)
    assert s["has_route"] is True and s["is_real"] is False  # ... the verdict did not


async def test_changing_the_type_changes_the_verdict(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(client, auth, [_workout(kind="WALKING")])
    assert (await _session(web))[0]["is_real"] is False
    await post_records(
        client, auth, [_workout(kind="HIKING", last_modified="2026-10-15T08:00:00Z")]
    )
    assert (await _session(web))[0]["is_real"] is True


# --------------------------------------------------------------------------- override


async def test_override_needs_a_session_and_the_csrf_header(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(client, auth, [_workout()])
    (s,) = await _session(web)
    url = f"/api/v1/exercise/sessions/{s['id']}/override"
    assert (await web.put(url, json={"value": True})).status_code == 403  # no X-SBH-Client
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    assert (await anonymous.put(url, json={"value": True}, headers=CSRF)).status_code == 401
    await anonymous.aclose()
    r = await web.put(
        "/api/v1/exercise/sessions/999999/override", json={"value": True}, headers=CSRF
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_session"
    assert (await web.put(url, json={"value": "maybe"}, headers=CSRF)).status_code == 422


async def test_override_wins_over_the_rule_both_ways(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [_hr("h1", START, END, _minutes(DAY, 18, 0, 30, 140)), _workout("a", method="active")],
    )
    (s,) = await _session(web)
    url = f"/api/v1/exercise/sessions/{s['id']}/override"
    assert s["is_real"] is True

    r = await web.put(url, json={"value": False}, headers=CSRF)
    assert r.json() == {"id": s["id"], "override": False, "is_real": False}
    (s,) = await _session(web)
    assert (s["override"], s["auto_real"], s["is_real"]) == (False, True, False)
    assert await _session(web, "real") == []

    r = await web.put(url, json={"value": True}, headers=CSRF)
    assert r.json()["is_real"] is True
    r = await web.put(url, json={"value": None}, headers=CSRF)  # back to automatic
    assert r.json() == {"id": s["id"], "override": None, "is_real": True}
    assert (await _session(web))[0]["override"] is None


async def test_override_survives_reingest_deletion_and_reinsertion(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(
        client, auth, [_workout("w1", kind="WALKING", method="automatic")]
    )  # not real by rule
    (s,) = await _session(web)
    await web.put(
        f"/api/v1/exercise/sessions/{s['id']}/override", json={"value": True}, headers=CSRF
    )
    assert (await _session(web))[0]["is_real"] is True

    # newer version of the record (route added, last_modified moves on)
    await post_records(
        client,
        auth,
        [
            _workout(
                "w1",
                kind="WALKING",
                method="automatic",
                route=True,
                last_modified="2026-10-15T08:00:00Z",
            )
        ],
    )
    assert (await _session(web))[0]["override"] is True

    # deleted in Health Connect and later re-created: same hc_id, the verdict is still there
    r = await post(
        client,
        auth,
        "deletions",
        {
            "device_id": DEVICE,
            "sync_id": "1f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a12",
            "items": [{"hc_id": "w1"}],
        },
    )
    assert r.status_code == 200 and await _session(web) == []
    await post_records(
        client,
        auth,
        [_workout("w1", kind="WALKING", method="automatic", last_modified="2026-10-16T08:00:00Z")],
    )
    (s,) = await _session(web)
    assert s["override"] is True and s["is_real"] is True


async def test_override_applies_to_every_copy_of_the_workout(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [
            _workout("w-watch", kind="WALKING", method="automatic", pkg="pkg.watch"),
            _workout("w-phone", kind="WALKING", method="automatic", pkg="pkg.phone"),
        ],
    )
    (s,) = await _session(web)
    await web.put(
        f"/api/v1/exercise/sessions/{s['id']}/override", json={"value": True}, headers=CSRF
    )
    (s,) = await _session(web)
    assert s["is_real"] is True
    # whichever copy ranks first later, the verdict follows the workout
    assert await _session(web, "real") != []


# --------------------------------------------------------------------------- day / night heart rate


async def _post_exercise_day(client: httpx.AsyncClient, auth: dict[str, str], kind: str) -> None:
    samples = (
        _minutes(DAY, 12, 0, 3, 70)  # a quiet midday
        + _minutes(DAY, 18, 0, 30, 150)  # the workout
        + _minutes(DAY, 18, 30, 30, 120)  # the 30 minutes of recovery
        + _minutes(DAY, 19, 0, 3, 72)  # back to normal
    )
    await post_records(
        client,
        auth,
        [
            _hr("h1", f"{DAY}T12:00:00+02:00", f"{DAY}T19:10:00+02:00", samples),
            _workout(kind=kind),
        ],
    )


async def test_daytime_heart_rate_excludes_a_real_workout_and_30_minutes_after(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_exercise_day(client, auth, "RUNNING")
    body = (await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}")).json()
    point = body["points"][0]
    assert point["day_n"] == 6 and point["day"] == pytest.approx(71, abs=1)  # 70x3 + 72x3
    assert body["include_workouts"] is False
    assert body["summary"]["day"]["avg"] == pytest.approx(71, abs=1)
    (w,) = body["workouts"]
    assert w["start"].startswith(f"{DAY}T16:00") and w["end"].startswith(f"{DAY}T16:30")
    assert w["recovery_end"].startswith(f"{DAY}T17:00")

    full = (
        await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}&include_workouts=true")
    ).json()
    assert full["include_workouts"] is True
    assert full["points"][0]["day_n"] == 66 and full["points"][0]["day"] > 120


async def _post_run(client: httpx.AsyncClient, auth: dict[str, str], minutes: int) -> None:
    samples = (
        _minutes(DAY, 12, 0, 3, 70)
        + _minutes(DAY, 18, 0, minutes, 150)  # the run
        + _minutes(DAY, 18, minutes, 30, 120)  # the 30 minutes after it
        + _minutes(DAY, 19, 30, 3, 72)
    )
    await post_records(
        client,
        auth,
        [
            _hr("h1", f"{DAY}T12:00:00+02:00", f"{DAY}T19:40:00+02:00", samples),
            _workout(end=f"{DAY}T18:{minutes:02d}:00+02:00"),
        ],
    )


async def test_a_run_under_15_minutes_is_not_real_and_not_excluded_from_the_daytime_hr(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_run(client, auth, 10)
    assert await _session(web, "real") == []
    body = (await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}")).json()
    assert body["workouts"] == []
    assert body["points"][0]["day_n"] == 3 + 10 + 30 + 3  # every sample is daytime


async def test_a_run_of_15_minutes_is_real_and_excluded_with_its_recovery(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_run(client, auth, 15)
    assert len(await _session(web, "real")) == 1
    body = (await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}")).json()
    assert len(body["workouts"]) == 1
    assert body["points"][0]["day_n"] == 3 + 3  # run and the 30 minutes after are left out
    report = (await web.get(f"/api/v1/report?from={DAY}&to={DAY}")).json()
    assert report["workouts"]["count"] == 1


async def test_a_short_run_is_left_out_of_the_report(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_run(client, auth, 10)
    report = (await web.get(f"/api/v1/report?from={DAY}&to={DAY}")).json()
    assert report["workouts"]["count"] == 0 and report["workouts"]["excluded"] == 1


async def test_walks_are_not_excluded_from_the_daytime_heart_rate(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_exercise_day(client, auth, "WALKING")  # a walk is not a real workout
    body = (await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}")).json()
    assert body["workouts"] == [] and body["points"][0]["day_n"] == 66


async def test_the_override_changes_what_the_daytime_heart_rate_excludes(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_exercise_day(client, auth, "RUNNING")
    (s,) = await _session(web)
    await web.put(
        f"/api/v1/exercise/sessions/{s['id']}/override", json={"value": False}, headers=CSRF
    )
    body = (await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}")).json()
    assert body["workouts"] == [] and body["points"][0]["day_n"] == 66


async def test_the_night_is_not_touched_by_workouts(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _post_exercise_day(client, auth, "RUNNING")
    night = _minutes("2026-10-13", 23, 30, 20, 50)
    await post_records(
        client,
        auth,
        [
            _hr(
                "h-night",
                f"{DAY.replace('14', '13')}T23:30:00+02:00",
                f"{DAY.replace('14', '13')}T23:50:00+02:00",
                night,
            )
        ],
    )
    with_ = (await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}")).json()
    without = (
        await web.get(f"/api/v1/heart/daypart?from={DAY}&to={DAY}&include_workouts=true")
    ).json()
    assert with_["points"][0]["night"] == without["points"][0]["night"] == 50
    assert with_["points"][0]["night_n"] == without["points"][0]["night_n"] == 20


# --------------------------------------------------------------------------- report


async def test_the_report_counts_only_real_workouts(seeded: None, web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=9)
    everything = (await web.get(f"/api/v1/exercise/sessions?from={first}&to={TODAY}")).json()
    assert everything["total_count"] > everything["real_count"] > 0
    report = (await web.get(f"/api/v1/report?from={first}&to={TODAY}")).json()
    w = report["workouts"]
    assert w["scope"] == "real" and w["count"] == everything["real_count"]
    assert w["excluded"] == everything["total_count"] - everything["real_count"]
    by = {m["key"]: m for m in report["metrics"]}
    assert by["workouts"]["sessions"] == everything["real_count"]
    real = (await web.get(f"/api/v1/exercise/sessions?from={first}&to={TODAY}&scope=real")).json()
    assert by["workouts"]["current"]["total"] == pytest.approx(real["summary"]["duration_s"])
    daily = (await web.get(f"/api/v1/report/daily?from={first}&to={TODAY}")).json()
    n = sum(row["values"].get("workouts_n") or 0 for row in daily["rows"])
    assert n == everything["real_count"]


async def test_the_seed_follows_the_rule(seeded: None, web: httpx.AsyncClient) -> None:
    first = TODAY - timedelta(days=9)
    rows = (await web.get(f"/api/v1/exercise/sessions?from={first}&to={TODAY}")).json()["sessions"]
    walks = [s for s in rows if s["type"] == "WALKING"]
    short = [s for s in rows if s["type"] != "WALKING" and s["duration_s"] < 15 * 60]
    others = [s for s in rows if s["type"] != "WALKING" and s["duration_s"] >= 15 * 60]
    assert walks and short and others
    assert all(not s["is_real"] and s["auto_rule"] == "type" for s in walks)
    assert any(s["started_by_user"] for s in walks) and any(not s["started_by_user"] for s in walks)
    # a started, non-walking session under the minimum is still not real
    assert all(not s["is_real"] and s["auto_rule"] == "duration" for s in short)
    assert any(s["started_by_user"] for s in short)
    assert all(s["is_real"] for s in others)  # running / cycling / gym, with or without HR or GPS
    assert any(s["is_real"] and not s["has_hr"] for s in others)  # the gym session, watch off
    assert any(s["is_real"] and not s["has_route"] for s in others)
    assert any(s["has_route"] for s in rows)
