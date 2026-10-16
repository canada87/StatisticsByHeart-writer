"""Idempotency, validation isolation, soft delete, series samples."""

import httpx
from fastapi import FastAPI

from tests.helpers import (
    DEVICE,
    SYNC,
    post,
    post_records,
    record,
    records_body,
    rows,
    scalar,
    steps,
)

A = ("2026-10-14T08:00:00+02:00", "2026-10-14T08:15:00+02:00")


def _batch() -> list[dict]:
    return [
        steps("s1", *A, 100),
        steps("s2", "2026-10-14T08:15:00+02:00", "2026-10-14T08:30:00+02:00", 200),
        record("Weight", "w1", "2026-10-14T07:00:00+02:00", None, {"value": 78.2}),
    ]


async def test_same_batch_twice_creates_no_duplicates(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    first = await post_records(client, auth, _batch())
    assert (first["received"], first["inserted"], first["updated"], first["unchanged"]) == (
        3,
        3,
        0,
        0,
    )
    assert first["rejected"] == []

    second = await post_records(client, auth, _batch())
    assert (second["received"], second["upserted"], second["unchanged"]) == (3, 0, 3)

    assert await scalar(app, "SELECT count(*) FROM health_record") == 3
    steps_sum = await scalar(
        app, "SELECT sum_value FROM daily_metric WHERE type='Steps' AND source='computed'"
    )
    assert steps_sum == 300


async def test_gzip_body_is_accepted(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    result = await post_records(client, auth, _batch(), gz=True)
    assert result["inserted"] == 3
    assert await scalar(app, "SELECT count(*) FROM health_record") == 3


async def test_newer_last_modified_updates_older_is_ignored(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [steps("s1", *A, 100)])

    newer = steps("s1", *A, 150, last_modified="2026-10-14T21:00:00Z")
    assert (await post_records(client, auth, [newer]))["updated"] == 1
    assert await scalar(app, "SELECT (data->>'value')::float FROM health_record") == 150

    older = steps("s1", *A, 999, last_modified="2026-10-14T19:00:00Z")
    result = await post_records(client, auth, [older])
    assert result["unchanged"] == 1 and result["upserted"] == 0
    assert await scalar(app, "SELECT (data->>'value')::float FROM health_record") == 150
    assert await scalar(app, "SELECT sum_value FROM daily_metric WHERE type='Steps'") == 150


async def test_invalid_records_are_rejected_individually(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    good = steps("ok", *A, 10)
    bad_value = steps("neg", *A, -5)
    bad_type = record("Teleportation", "tp", *A, {"value": 1})
    naive = steps("naive", "2026-10-14T08:00:00", "2026-10-14T08:15:00", 5)
    missing_end = record("Steps", "noend", A[0], None, {"value": 5})
    unknown_field = steps("extra", *A, 5)
    unknown_field["data"]["secret_extra"] = 1

    result = await post_records(
        client,
        auth,
        [bad_value, good, bad_type, naive, missing_end, unknown_field, {"nonsense": True}],
    )
    assert result["received"] == 7 and result["inserted"] == 1
    by_index = {r["index"]: r for r in result["rejected"]}
    assert sorted(by_index) == [0, 2, 3, 4, 5, 6]
    assert by_index[2]["reason"] == "unsupported_type"
    assert by_index[0]["reason"] == "invalid_record" and by_index[0]["hc_id"] == "neg"
    # details never echo values
    assert "-5" not in (by_index[0]["detail"] or "")
    assert await scalar(app, "SELECT count(*) FROM health_record") == 1


async def test_duplicate_inside_batch_keeps_latest(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    a = steps("dup", *A, 100, last_modified="2026-10-14T20:00:00Z")
    b = steps("dup", *A, 120, last_modified="2026-10-14T20:05:00Z")
    result = await post_records(client, auth, [a, b])
    assert result["inserted"] == 1 and result["unchanged"] == 1
    assert await scalar(app, "SELECT (data->>'value')::float FROM health_record") == 120


async def test_batch_over_limit_is_413(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    body = records_body([steps(f"s{i}", *A, 1) for i in range(501)])
    r = await post(client, auth, "records", body)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "batch_too_large"


async def test_malformed_envelope_is_422_without_echoing_input(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    r = await client.post(
        "/api/v1/ingest/records",
        json={"device_id": "not-a-uuid-SECRETVALUE", "sync_id": SYNC, "records": []},
        headers=auth,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "SECRETVALUE" not in r.text


async def test_invalid_json_and_corrupt_gzip(
    client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    r = await client.post(
        "/api/v1/ingest/records",
        content=b"{nope",
        headers={**auth, "Content-Type": "application/json"},
    )
    assert r.status_code == 422  # FastAPI's JSON decode error is a validation error
    r = await client.post(
        "/api/v1/ingest/records",
        content=b"definitely not gzip",
        headers={**auth, "Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_body"


async def test_heart_rate_samples_are_exploded_and_idempotent(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    samples = [
        {"time": f"2026-10-14T10:{m:02d}:00+02:00", "value": 60 + m} for m in range(0, 30, 5)
    ]
    samples.append(samples[0])  # duplicate timestamp inside the record collapses
    hr = record(
        "HeartRate",
        "hr1",
        "2026-10-14T10:00:00+02:00",
        "2026-10-14T10:30:00+02:00",
        {"samples": samples},
    )
    assert (await post_records(client, auth, [hr]))["inserted"] == 1
    assert await scalar(app, "SELECT count(*) FROM health_sample") == 6
    assert (await post_records(client, auth, [hr]))["unchanged"] == 1
    assert await scalar(app, "SELECT count(*) FROM health_sample") == 6
    assert await scalar(app, "SELECT (data->>'sample_count')::int FROM health_record") == 6

    # a modified record replaces its samples (no leftovers)
    hr2 = record(
        "HeartRate",
        "hr1",
        "2026-10-14T10:00:00+02:00",
        "2026-10-14T10:30:00+02:00",
        {"samples": samples[:2]},
        last_modified="2026-10-14T22:00:00Z",
    )
    assert (await post_records(client, auth, [hr2]))["updated"] == 1
    assert await scalar(app, "SELECT count(*) FROM health_sample") == 2


async def test_deletion_soft_deletes_and_recomputes(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    hr = record(
        "HeartRate",
        "hr1",
        "2026-10-14T10:00:00+02:00",
        "2026-10-14T10:10:00+02:00",
        {"samples": [{"time": "2026-10-14T10:00:00+02:00", "value": 70}]},
    )
    await post_records(client, auth, [steps("s1", *A, 100), steps("s2", *A, 50, pkg="pkg.b"), hr])

    r = await post(
        client,
        auth,
        "deletions",
        {
            "device_id": DEVICE,
            "sync_id": SYNC,
            "items": [
                {"hc_id": "s1"},
                {"hc_id": "hr1", "type": "HeartRate"},
                {"hc_id": "ghost"},
                {"nonsense": True},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["received"], body["deleted"], body["not_found"]) == (4, 2, 1)
    assert [x["index"] for x in body["rejected"]] == [3]

    assert await scalar(app, "SELECT count(*) FROM health_record WHERE deleted_at IS NOT NULL") == 2
    assert await scalar(app, "SELECT count(*) FROM health_sample") == 0
    # remaining steps come only from the surviving record
    assert await scalar(app, "SELECT sum_value FROM daily_metric WHERE type='Steps'") == 50
    assert await scalar(app, "SELECT count(*) FROM daily_metric WHERE type='HeartRate'") == 0

    # deleting again is reported, not an error
    again = await post(
        client,
        auth,
        "deletions",
        {"device_id": DEVICE, "sync_id": SYNC, "items": [{"hc_id": "s1"}]},
    )
    assert again.json()["already_deleted"] == 1 and again.json()["deleted"] == 0


async def test_deleted_record_is_not_resurrected_by_stale_resend(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    rec = steps("s1", *A, 100)
    await post_records(client, auth, [rec])
    await post(
        client,
        auth,
        "deletions",
        {"device_id": DEVICE, "sync_id": SYNC, "items": [{"hc_id": "s1"}]},
    )

    stale = await post_records(client, auth, [rec])  # same last_modified: a retried old batch
    assert stale["unchanged"] == 1
    assert await scalar(app, "SELECT deleted_at IS NOT NULL FROM health_record") is True

    revived = await post_records(
        client, auth, [steps("s1", *A, 100, last_modified="2026-10-15T00:00:00Z")]
    )
    assert revived["updated"] == 1
    assert await scalar(app, "SELECT deleted_at IS NULL FROM health_record") is True
    assert await scalar(app, "SELECT sum_value FROM daily_metric WHERE type='Steps'") == 100


async def test_sync_run_counters_and_report(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [steps("s1", *A, 1), {"bad": 1}])
    r = await post(
        client,
        auth,
        "sync-report",
        {
            "device_id": DEVICE,
            "sync_id": SYNC,
            "mode": "incremental",
            "status": "partial",
            "started_at": "2026-10-14T08:00:00Z",
            "finished_at": "2026-10-14T08:00:05Z",
            "counts": {"records_sent": 2},
            "errors": [{"code": "type_read_failed", "type": "Power", "count": 1}],
        },
    )
    assert r.status_code == 200 and r.json() == {"ok": True, "sync_id": SYNC}
    run = (
        await rows(
            app,
            "SELECT status, mode, records_received, records_inserted, records_rejected, "
            "reported_counts FROM sync_run",
        )
    )[0]
    assert tuple(run[:5]) == ("partial", "incremental", 2, 1, 1)
    assert run[5] == {"records_sent": 2}
    assert await scalar(app, "SELECT count(*) FROM device") == 1


def _workout(route: bool, **kw: object) -> dict:
    data: dict[str, object] = {"exercise_type": "RUNNING", "title": "Run"}
    if route:
        data["route"] = [
            {"time": "2026-10-14T18:00:00+02:00", "lat": 0.0001, "lon": 0.0002},
            {"time": "2026-10-14T18:01:00+02:00", "lat": 0.0002, "lon": 0.0003},
        ]
    return record(
        "ExerciseSession",
        "w1",
        "2026-10-14T18:00:00+02:00",
        "2026-10-14T18:30:00+02:00",
        data,
        **kw,  # type: ignore[arg-type]
    )


async def test_same_last_modified_with_different_data_updates_the_record(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    """The Reader re-sends past workouts with their GPS route added, keeping last_modified."""
    first = await post_records(client, auth, [_workout(False)])
    assert first["inserted"] == 1
    assert await scalar(app, "SELECT data ? 'route' FROM health_record") is False

    again = await post_records(client, auth, [_workout(False)])  # identical: still a no-op
    assert (again["updated"], again["unchanged"]) == (0, 1)

    with_route = await post_records(client, auth, [_workout(True)])  # same last_modified
    assert (with_route["updated"], with_route["unchanged"]) == (1, 0)
    assert await scalar(app, "SELECT data ? 'route' FROM health_record") is True
    assert await scalar(app, "SELECT jsonb_array_length(data->'route') FROM health_record") == 2

    settled = await post_records(client, auth, [_workout(True)])
    assert (settled["updated"], settled["unchanged"]) == (0, 1)


async def test_same_last_modified_different_data_does_not_revive_a_deleted_record(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    await post_records(client, auth, [_workout(False)])
    await post(
        client,
        auth,
        "deletions",
        {"device_id": DEVICE, "sync_id": SYNC, "items": [{"hc_id": "w1"}]},
    )
    result = await post_records(client, auth, [_workout(True)])
    assert (result["updated"], result["unchanged"]) == (0, 1)
    assert await scalar(app, "SELECT deleted_at IS NOT NULL FROM health_record") is True


async def test_a_large_route_fits_in_a_gzip_request(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    """50 000 route points (the contract maximum) in one gzip-compressed session."""
    route = [
        {
            "time": "2026-10-14T18:00:00+02:00",
            "lat": 0.0001 + i * 1e-7,
            "lon": 0.0002 + i * 1e-7,
            "alt_m": 10.0,
        }
        for i in range(50_000)
    ]
    rec = record(
        "ExerciseSession",
        "big",
        "2026-10-14T18:00:00+02:00",
        "2026-10-14T19:00:00+02:00",
        {"exercise_type": "BIKING", "route": route},
    )
    result = await post_records(client, auth, [rec], gz=True)
    assert result["inserted"] == 1
    assert (
        await scalar(app, "SELECT jsonb_array_length(data->'route') FROM health_record") == 50_000
    )
    too_many = {**rec, "hc_id": "big2", "data": {**rec["data"], "route": route + route[:1]}}
    r = await post(client, auth, "records", records_body([too_many]), gz=True)
    assert r.status_code == 200 and len(r.json()["rejected"]) == 1  # 50 001 points: refused


async def test_an_oversized_body_is_a_413(client: httpx.AsyncClient, auth: dict[str, str]) -> None:
    from app.config import Settings  # noqa: F401  (documented limit: max_body_bytes, 32 MiB)

    blob = {"device_id": DEVICE, "sync_id": SYNC, "records": [], "pad": "x" * (33 * 1024 * 1024)}
    r = await post(client, auth, "records", blob, gz=True)
    assert r.status_code == 413 and r.json()["error"]["code"] == "body_too_large"


async def test_an_update_without_a_route_keeps_the_stored_route(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    """Route permission revoked in Health Connect: later versions of the session carry no route."""
    await post_records(client, auth, [_workout(True)])
    assert await scalar(app, "SELECT jsonb_array_length(data->'route') FROM health_record") == 2

    later = _workout(False)
    later["last_modified"] = "2026-10-15T09:00:00Z"
    later["data"]["title"] = "Run (renamed)"
    result = await post_records(client, auth, [later])
    assert result["updated"] == 1
    assert await scalar(app, "SELECT data->>'title' FROM health_record") == "Run (renamed)"
    assert await scalar(app, "SELECT jsonb_array_length(data->'route') FROM health_record") == 2

    # same version re-sent without the route: still a no-op, the route stays
    again = await post_records(client, auth, [later])
    assert (again["updated"], again["unchanged"]) == (0, 1)
    # the old payload at the old last_modified without a route is not an update either
    stale = await post_records(client, auth, [_workout(False)])
    assert (stale["updated"], stale["unchanged"]) == (0, 1)
    assert await scalar(app, "SELECT jsonb_array_length(data->'route') FROM health_record") == 2

    # an explicit new route replaces the old one
    newer = _workout(True)
    newer["last_modified"] = "2026-10-16T09:00:00Z"
    newer["data"]["route"] = newer["data"]["route"][:1]
    await post_records(client, auth, [newer])
    assert await scalar(app, "SELECT jsonb_array_length(data->'route') FROM health_record") == 1
