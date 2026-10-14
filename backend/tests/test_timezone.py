"""Local-day attribution: the record's own offset wins; Europe/Rome only as fallback."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from app.timeutil import local_date
from tests.helpers import post_records, record, rows, scalar, steps

ROME = ZoneInfo("Europe/Rome")


def test_offset_of_the_record_wins_over_server_zone() -> None:
    ts = datetime(2026, 10, 14, 2, 0, tzinfo=UTC)  # 04:00 in Rome, 21:00 the day before in New York
    assert str(local_date(ts, -4 * 3600, ROME)) == "2026-10-13"
    assert str(local_date(ts, None, ROME)) == "2026-10-14"
    assert str(local_date(ts, 2 * 3600, ROME)) == "2026-10-14"


@pytest.mark.parametrize(
    ("utc_iso", "expected"),
    [
        ("2026-10-24T22:30:00+00:00", "2026-10-25"),  # still CEST (+2): 00:30 on the 25th
        ("2026-10-25T22:30:00+00:00", "2026-10-25"),  # after the DST change, CET (+1): 23:30
        ("2026-10-25T23:30:00+00:00", "2026-10-26"),  # CET: 00:30 on the 26th
    ],
)
def test_fallback_handles_dst_change(utc_iso: str, expected: str) -> None:
    assert str(local_date(datetime.fromisoformat(utc_iso), None, ROME)) == expected


async def test_steps_are_attributed_to_the_local_day_of_the_record(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    # 23:30 CEST on the 14th = 21:30Z: the 14th locally, whatever the offset says elsewhere.
    rome_evening = steps("a", "2026-10-14T23:30:00+02:00", "2026-10-14T23:45:00+02:00", 100)
    # 01:00Z on the 15th, but the phone was in UTC-5: still the 14th for the user.
    traveller = steps("b", "2026-10-15T01:00:00Z", "2026-10-15T01:15:00Z", 40, offset=-5 * 3600)
    # no offset: falls back to Rome (CEST): 22:30Z on the 14th is 00:30 on the 15th.
    no_offset = steps("c", "2026-10-14T22:30:00Z", "2026-10-14T22:45:00Z", 7, offset=None)
    await post_records(client, auth, [rome_evening, traveller, no_offset])

    by_day = {
        str(d): v
        for d, v in await rows(
            app, "SELECT local_date, sum_value FROM daily_metric WHERE type='Steps'"
        )
    }
    assert by_day == {"2026-10-14": 140, "2026-10-15": 7}
    assert await scalar(app, "SELECT start_offset_s FROM health_record WHERE hc_id='b'") == -18000
    # timestamps are stored as UTC instants
    assert await scalar(app, "SELECT start_ts FROM health_record WHERE hc_id='a'") == datetime(
        2026, 10, 14, 21, 30, tzinfo=UTC
    )


async def test_sleep_counts_for_the_wake_up_day(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    sleep = record(
        "SleepSession", "sl1", "2026-10-13T23:00:00+02:00", "2026-10-14T06:30:00+02:00", {}
    )
    await post_records(client, auth, [sleep])
    assert str(await scalar(app, "SELECT local_date FROM health_record")) == "2026-10-14"
    days = [str(d) for (d,) in await rows(app, "SELECT local_date FROM daily_metric")]
    assert days == ["2026-10-14"]
    assert await scalar(app, "SELECT sum_value FROM daily_metric") == 7.5 * 3600


async def test_heart_rate_samples_get_their_own_local_day(
    client: httpx.AsyncClient, auth: dict[str, str], app: FastAPI
) -> None:
    hr = record(
        "HeartRate",
        "hr",
        "2026-10-14T23:55:00+02:00",
        "2026-10-15T00:05:00+02:00",
        {
            "samples": [
                {"time": "2026-10-14T23:58:00+02:00", "value": 60},
                {"time": "2026-10-15T00:02:00+02:00", "value": 80},
            ]
        },
    )
    await post_records(client, auth, [hr])
    got = {
        str(d): c
        for d, c in await rows(
            app, "SELECT local_date, count FROM daily_metric WHERE type='HeartRate'"
        )
    }
    assert got == {"2026-10-14": 1, "2026-10-15": 1}
