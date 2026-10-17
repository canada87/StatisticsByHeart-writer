"""per_day: week/month buckets hold the mean per day, so a partial month is not a collapse."""

import httpx
import pytest

from tests.helpers import post_records, record, steps

JAN = ("2026-01-10", "2026-01-11")  # two days of January
FEB = ("2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05")  # four days of February


def _day_steps(day: str, n: int, hc: str) -> list[dict]:
    """n separate one-hour records of 1000 steps on that day (n records, 1000 x n steps)."""
    return [
        steps(f"{hc}-{i}", f"{day}T{8 + i:02d}:00:00+01:00", f"{day}T{9 + i:02d}:00:00+01:00", 1000)
        for i in range(n)
    ]


async def test_the_monthly_value_can_be_the_mean_per_day(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    recs: list[dict] = []
    recs += _day_steps(JAN[0], 1, "j0")  # 1000 steps, 1 record
    recs += _day_steps(JAN[1], 3, "j1")  # 3000 steps, 3 records
    for k, day in enumerate(FEB):
        recs += _day_steps(day, 2, f"f{k}")  # 2000 steps a day
    await post_records(client, auth, recs)
    base = "/api/v1/metrics/Steps/series?from=2026-01-01&to=2026-02-28&bucket=month&agg=sum"

    total = (await web.get(base)).json()
    assert [p["v"] for p in total["points"]] == [4000, 8000] and total["per_day"] is False

    mean = (await web.get(base + "&per_day=true")).json()
    assert mean["per_day"] is True and mean["bucket"] == "month"
    jan, feb = mean["points"]
    # two days of January: the PLAIN mean of the days (2000), not weighted by records (2500)
    assert jan["v"] == pytest.approx(2000) and jan["days"] == 2
    assert feb["v"] == pytest.approx(2000) and feb["days"] == 4
    # the same pace in a short and in a whole month: no fake collapse
    assert total["points"][0]["v"] < total["points"][1]["v"] and jan["v"] == feb["v"]


async def test_sleep_per_night_and_the_number_of_nights(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    sleep = {"title": "Night", "stages": []}
    await post_records(
        client,
        auth,
        [
            record(
                "SleepSession",
                "n1",
                "2026-03-10T00:00:00+01:00",
                "2026-03-10T06:00:00+01:00",
                sleep,
            ),
            record(
                "SleepSession",
                "n2",
                "2026-03-11T00:00:00+01:00",
                "2026-03-11T08:00:00+01:00",
                sleep,
            ),
        ],
    )
    q = "/api/v1/metrics/SleepSession/series?from=2026-03-01&to=2026-03-31&bucket=month"
    total = (await web.get(q)).json()["points"][0]
    assert total["v"] == 14 * 3600 and total["days"] == 2  # the total of the month: not a night
    mean = (await web.get(q + "&per_day=true")).json()["points"][0]
    assert mean["v"] == 7 * 3600 and mean["days"] == 2  # seven hours per night


async def test_per_day_only_changes_week_and_month_buckets(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    await post_records(client, auth, _day_steps("2026-01-10", 3, "d"))
    q = "/api/v1/metrics/Steps/series?from=2026-01-10&to=2026-01-16&agg=sum"
    day = (await web.get(q + "&bucket=day&per_day=true")).json()
    assert day["per_day"] is False and day["points"][0]["v"] == 3000  # a day is already a day
    week = (await web.get(q + "&bucket=week&per_day=true")).json()
    assert (
        week["per_day"] is True
        and week["points"][0]["v"] == 3000
        and week["points"][0]["days"] == 1
    )
    # heart-rate style (avg) series: plain mean of the daily means too
    hr = (
        await web.get("/api/v1/metrics/Steps/series?from=2026-01-10&to=2026-01-16&bucket=week")
    ).json()
    assert hr["per_day"] is False


async def test_the_previous_period_follows_per_day(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str]
) -> None:
    recs = _day_steps("2026-01-05", 2, "a") + _day_steps("2026-01-20", 4, "b")
    await post_records(client, auth, recs)
    r = (
        await web.get(
            "/api/v1/metrics/Steps/series?from=2026-01-15&to=2026-01-31&bucket=week&agg=sum&per_day=true&compare=true"
        )
    ).json()
    assert r["previous_summary"]["points"] >= 1
    assert any(p["v"] == pytest.approx(4000) for p in r["points"])
