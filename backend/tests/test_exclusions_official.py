"""An exclusion also overrides the official Health Connect aggregate of its day (ADR 0011, 0.9.1).

Real case: a 15.4 kg weight of someone else shares the day with the real 65.85 kg. The official
Health Connect daily average, (15.4 + 65.85) / 2 = 40.625, includes both, and used to win over the
computed value, which skips the excluded record.
"""

import httpx
from fastapi import FastAPI

from tests.helpers import DEVICE, SYNC, computed, post, post_records, record

W = {"X-SBH-Client": "web"}
D0, D1, D2, D3 = "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"
MEAN = (15.4 + 65.85) / 2


def _lm(hour: int = 8) -> str:
    return f"2026-10-30T{hour:02d}:00:00Z"


def _weight(hc_id: str, day: str, kg: float, hour: str, pkg: str):
    return record(
        "Weight", hc_id, f"{day}T{hour}:00+01:00", None, {"value": kg}, pkg=pkg, last_modified=_lm()
    )


async def _official(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    items: list[dict],
    snapshot: str = "2026-10-30T09:00:00Z",
) -> None:
    body = {
        "device_id": DEVICE,
        "sync_id": SYNC,
        "items": [{**i, "snapshot_at": snapshot} for i in items],
    }
    r = await post(client, auth, "daily-aggregates", body)
    assert r.status_code == 200, r.text


async def _series(web: httpx.AsyncClient, type_: str, **q: str) -> dict[str, dict]:
    extra = "".join(f"&{k}={v}" for k, v in q.items())
    r = await web.get(f"/api/v1/metrics/{type_}/series?from={D0}&to={D3}&bucket=day&ma=true{extra}")
    assert r.status_code == 200, r.text
    return {p["t"]: p for p in r.json()["points"]}


async def _seed_weights(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    await post_records(
        client,
        auth,
        [
            _weight("ok0", D0, 65.5, "07:00", "scale"),
            _weight("ok1", D1, 65.85, "19:00", "scale"),
            _weight("kid1", D1, 15.4, "07:38", "qingniu"),  # the same measure from two apps
            _weight("kid1b", D1, 15.4, "07:38", "withings"),
            _weight("ok2", D2, 66.0, "07:00", "scale"),
        ],
    )
    await _official(
        client,
        auth,
        [
            {"date": D0, "type": "Weight", "avg": 65.5, "min": 65.5, "max": 65.5, "count": 1},
            {"date": D1, "type": "Weight", "avg": MEAN, "min": 15.4, "max": 65.85, "count": 2},
            {"date": D2, "type": "Weight", "avg": 66.0, "min": 66.0, "max": 66.0, "count": 1},
        ],
    )


async def _foreign(web: httpx.AsyncClient) -> dict:
    r = await web.get(f"/api/v1/measures?type=Weight&from={D1}&to={D1}")
    return next(m for m in r.json()["measures"] if m["value"] == 15.4)


async def test_the_official_average_that_includes_the_excluded_weight_is_ignored(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await _seed_weights(client, auth)
    before = await _series(web, "Weight")
    assert before[D1]["v"] == MEAN  # the official aggregate wins until something is excluded

    foreign = await _foreign(web)
    assert len(foreign["ids"]) == 2
    r = await web.post(
        "/api/v1/exclusions", json={"record_id": foreign["ids"][0], "reason": "figlio"}, headers=W
    )
    assert r.status_code == 201

    after = await _series(web, "Weight")
    assert after[D1]["v"] == 65.85
    assert after[D0]["v"] == 65.5 and after[D2]["v"] == 66.0  # other days keep their official value
    # moving average of the three days: no trace of 40.625 or 15.4 left
    assert abs(after[D2]["ma"] - (65.5 + 65.85 + 66.0) / 3) < 1e-6
    s = (
        await web.get(f"/api/v1/metrics/Weight/series?from={D0}&to={D3}&bucket=day&band=true")
    ).json()
    assert s["summary"]["min"] == 65.5 and s["summary"]["max"] == 66.0
    assert all(p["lo"] is None or p["lo"] > 60 for p in s["points"])

    # the official row is stored untouched: only reading ignores it
    assert (await computed(app, "Weight", D1, "hc_official"))[1] == MEAN

    # report and daily CSV source
    daily = (await web.get(f"/api/v1/report/daily?from={D0}&to={D3}")).json()
    assert {r["date"]: r["values"]["weight_kg"] for r in daily["rows"]}[D1] == 65.85
    report = (await web.get(f"/api/v1/report?from={D0}&to={D3}")).json()
    wm = next(m for m in report["metrics"] if m["key"] == "weight")
    assert wm["current"]["min"] == 65.5 and wm["current"]["max"] == 66.0

    # restoring brings the official aggregate back, with no recomputation
    group = (await web.get("/api/v1/exclusions")).json()["items"][0]["group_id"]
    assert (await web.delete(f"/api/v1/exclusions/{group}", headers=W)).status_code == 204
    assert (await _series(web, "Weight"))[D1]["v"] == MEAN


async def test_a_resent_official_aggregate_stays_ignored_while_the_exclusion_lasts(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _seed_weights(client, auth)
    foreign = await _foreign(web)
    await web.post("/api/v1/exclusions", json={"record_id": foreign["ids"][0]}, headers=W)
    assert (await _series(web, "Weight"))[D1]["v"] == 65.85

    # the Reader sends the day again, with a newer snapshot and a slightly different average
    await _official(
        client,
        auth,
        [{"date": D1, "type": "Weight", "avg": 40.7, "min": 15.4, "max": 65.9, "count": 2}],
        snapshot="2026-10-31T09:00:00Z",
    )
    assert (await _series(web, "Weight"))[D1]["v"] == 65.85
    # a full re-ingest of the records does not bring the day back either
    await _seed_weights(client, auth)
    assert (await _series(web, "Weight"))[D1]["v"] == 65.85


async def test_a_day_without_exclusions_keeps_preferring_the_official_value(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _seed_weights(client, auth)
    # exclude the real weight of another day: D1 is not touched
    r = await web.get(f"/api/v1/measures?type=Weight&from={D2}&to={D2}")
    await web.post(
        "/api/v1/exclusions", json={"record_id": r.json()["measures"][0]["ids"][0]}, headers=W
    )
    pts = await _series(web, "Weight")
    assert pts[D1]["v"] == MEAN and pts[D2]["v"] is None


async def test_a_record_deleted_in_health_connect_no_longer_overrides_the_official_value(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await _seed_weights(client, auth)
    foreign = await _foreign(web)
    await web.post("/api/v1/exclusions", json={"record_id": foreign["ids"][0]}, headers=W)
    assert (await _series(web, "Weight"))[D1]["v"] == 65.85
    r = await post(
        client,
        auth,
        "deletions",
        {"device_id": DEVICE, "sync_id": SYNC, "items": [{"hc_id": "kid1"}, {"hc_id": "kid1b"}]},
    )
    assert r.status_code == 200 and r.json()["deleted"] == 2, r.text
    # HC dropped the measure, so its next official aggregate no longer contains it
    await _official(
        client,
        auth,
        [{"date": D1, "type": "Weight", "avg": 65.85, "min": 65.85, "max": 65.85, "count": 1}],
        snapshot="2026-10-31T11:00:00Z",
    )
    assert (await _series(web, "Weight"))[D1]["v"] == 65.85


async def test_spo2_and_resting_heart_rate_follow_the_same_rule(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [
            record(
                "OxygenSaturation",
                "s1",
                f"{D1}T03:00:00+01:00",
                None,
                {"value": 97},
                last_modified=_lm(),
            ),
            record(
                "OxygenSaturation",
                "s2",
                f"{D1}T04:00:00+01:00",
                None,
                {"value": 71},
                last_modified=_lm(),
            ),
            record(
                "RestingHeartRate",
                "r1",
                f"{D1}T07:00:00+01:00",
                None,
                {"value": 56},
                last_modified=_lm(),
            ),
            record(
                "RestingHeartRate",
                "r2",
                f"{D1}T08:00:00+01:00",
                None,
                {"value": 120},
                last_modified=_lm(),
            ),
        ],
    )
    await _official(
        client,
        auth,
        [
            {"date": D1, "type": "OxygenSaturation", "avg": 84, "min": 71, "max": 97, "count": 2},
            {"date": D1, "type": "RestingHeartRate", "avg": 88, "min": 56, "max": 120, "count": 2},
        ],
    )
    assert (await _series(web, "OxygenSaturation"))[D1]["v"] == 84
    assert (await _series(web, "RestingHeartRate"))[D1]["v"] == 88
    for type_, value in (("OxygenSaturation", 71), ("RestingHeartRate", 120)):
        ms = (await web.get(f"/api/v1/measures?type={type_}&from={D1}&to={D1}")).json()["measures"]
        mid = next(m for m in ms if m["value"] == value)["ids"][0]
        assert (
            await web.post("/api/v1/exclusions", json={"record_id": mid}, headers=W)
        ).status_code == 201
    assert (await _series(web, "OxygenSaturation"))[D1]["v"] == 97
    assert (await _series(web, "RestingHeartRate"))[D1]["v"] == 56
    report = (await web.get(f"/api/v1/report?from={D0}&to={D3}")).json()
    by = {m["key"]: m for m in report["metrics"]}
    assert by["spo2"]["current"]["min"] == 97 and by["resting_hr"]["current"]["max"] == 56
    today = (await web.get("/api/v1/summary/today")).json()
    assert today is not None


async def test_sleep_uses_the_wake_day_and_the_reconciliation_says_why(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(
        client,
        auth,
        [
            record(
                "SleepSession",
                "n1",
                f"{D0}T23:00:00+01:00",
                f"{D1}T07:00:00+01:00",
                {},
                last_modified=_lm(),
            ),
            record(
                "SleepSession",
                "kid",
                f"{D1}T13:00:00+01:00",
                f"{D1}T14:30:00+01:00",
                {},
                pkg="other",
                last_modified=_lm(),
            ),
        ],
    )
    await _official(client, auth, [{"date": D1, "type": "SleepSession", "sum": 8 * 3600 + 5400}])
    assert (await _series(web, "SleepSession"))[D1]["v"] == 8 * 3600 + 5400
    ms = (await web.get(f"/api/v1/measures?type=SleepSession&from={D1}&to={D1}")).json()["measures"]
    kid = next(m for m in ms if m["value"] == 5400)
    await web.post("/api/v1/exclusions", json={"record_id": kid["ids"][0]}, headers=W)
    assert (await _series(web, "SleepSession"))[D1]["v"] == 8 * 3600

    rec = (
        await web.get(f"/api/v1/data/reconciliation?from={D0}&to={D3}&types=SleepSession")
    ).json()
    row = next(r for r in rec["rows"] if r["date"] == D1)
    # both values stay visible there, flagged: this is the place that explains the difference
    assert row["official_ignored"] is True
    assert row["official"] == 8 * 3600 + 5400 and row["computed"] == 8 * 3600
    assert all(r["official_ignored"] is False for r in rec["rows"] if r["date"] != D1)
