"""Heart Points: exact thresholds, max not sum, carry-forward, source de-dup, weeks, settings."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.config import Settings
from app.services import heartpoints as hp
from app.services import maintenance, points_api
from app.services.daily import Row
from tests.conftest import TODAY
from tests.helpers import DEVICE, post, post_records, record, rows, scalar

DAY = TODAY - timedelta(days=21)  # a past day, far from the running week
D = DAY.isoformat()
HR_MAX_1990 = int(205.8 - 0.685 * (DAY.year - 1990) + 0.5)  # fictitious 1990 birth year, for DAY


def _s(**kw: object) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/x", **kw)  # type: ignore[arg-type]


def _utc(h: int, m: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, h, m, tzinfo=UTC)


# --------------------------------------------------------------------------- thresholds (pure)


@pytest.mark.parametrize(
    ("pct", "points"), [(49, 0), (49.9, 0), (50, 1), (69, 1), (69.9, 1), (70, 2), (95, 2)]
)
def test_heart_rate_thresholds_are_exact_at_50_and_70_percent(pct: float, points: int) -> None:
    assert hp.hr_points(pct, 100) == points  # HRmax 100: bpm == percent
    assert hp.hr_points(pct * 2, 200) == points  # and the same at another HRmax


@pytest.mark.parametrize(
    ("steps", "points"),
    [(0, 0), (99, 0), (99.9, 0), (100, 1), (129, 1), (129.9, 1), (130, 2), (180, 2)],
)
def test_cadence_thresholds_are_exact_at_100_and_130(steps: float, points: int) -> None:
    assert hp.cadence_points(steps) == points


@pytest.mark.parametrize(
    ("h", "c", "expected"),
    [(0, 0, 0), (1, 0, 1), (0, 2, 2), (1, 2, 2), (2, 1, 2), (1, 1, 1), (2, 2, 2)],
)
def test_a_minute_scores_the_maximum_never_the_sum(h: int, c: int, expected: int) -> None:
    assert hp.minute_points(h, c) == expected


def test_the_constants_are_the_documented_ones() -> None:
    assert (hp.HR_MODERATE_PCT, hp.HR_VIGOROUS_PCT) == (50, 70)
    assert (hp.CADENCE_MODERATE, hp.CADENCE_VIGOROUS) == (100, 130)
    assert (hp.MODERATE_POINTS, hp.VIGOROUS_POINTS) == (1, 2)
    assert timedelta(minutes=2) == hp.HR_CARRY_MAX and timedelta(minutes=60) == hp.STEPS_MAX_SPAN
    assert hp.ACTIVE_CADENCE_MIN == 60 and hp.RULES_VERSION == 2
    assert (hp.HR_MAX_INTERCEPT, hp.HR_MAX_SLOPE) == (205.8, 0.685)
    assert hp.WEEKLY_GOAL == 150


# --------------------------------------------------------------------------- HRmax (pure)


def test_hr_max_comes_from_the_birth_year_at_the_date_of_the_day() -> None:
    s = _s(birth_year=1990)
    assert hp.hr_max_for(s, date(2026, 5, 1)) == (
        181,
        "birth_year",
    )  # age 36: 205.8 - 24.66 = 181.14
    assert hp.hr_max_for(s, date(2030, 5, 1)) == (178, "birth_year")  # 4 years on: 178.4


@pytest.mark.parametrize(
    ("age", "expected"),
    [(20, 192), (30, 185), (40, 178), (50, 172), (60, 165), (70, 158)],
)
def test_hr_max_formula_is_205_8_minus_0_685_age_rounded_to_the_nearest(
    age: int, expected: int
) -> None:
    # 205.8 - 0.685 x age: 192.1, 185.25, 178.4, 171.55, 164.7, 157.85
    assert hp.hr_max_for(_s(birth_year=2026 - age), date(2026, 5, 1)) == (expected, "birth_year")


def test_hr_max_rounds_half_up_at_the_boundary() -> None:
    # age 8: 205.8 - 5.48 = 200.32 -> 200; age 12: 205.8 - 8.22 = 197.58 -> 198
    assert hp.hr_max_for(_s(birth_year=2018), date(2026, 5, 1))[0] == 200
    assert hp.hr_max_for(_s(birth_year=2014), date(2026, 5, 1))[0] == 198


def test_the_override_wins_over_the_birth_year() -> None:
    assert hp.hr_max_for(_s(birth_year=1990, hr_max=195), date(2026, 5, 1)) == (195, "override")
    assert hp.hr_max_for(_s(hr_max=190), date(2026, 5, 1)) == (190, "override")


def test_without_age_or_override_there_is_no_hr_max_and_nonsense_is_ignored() -> None:
    assert hp.hr_max_for(_s(), date(2026, 5, 1)) == (None, None)
    assert hp.hr_max_for(_s(birth_year=2030), date(2026, 5, 1)) == (None, None)  # not born yet
    assert hp.hr_max_for(_s(birth_year=1850), date(2026, 5, 1)) == (None, None)
    assert hp.hr_max_for(_s(hr_max=20), date(2026, 5, 1)) == (None, None)
    assert hp.hr_max_for(_s(birth_year=1990, hr_max=20), date(2026, 5, 1))[1] == "birth_year"


def test_empty_environment_values_mean_unset() -> None:
    s = _s(birth_year="", hr_max=" ")
    assert s.birth_year is None and s.hr_max is None


# --------------------------------------------------------------------------- carry-forward (pure)


def test_a_minute_without_samples_repeats_the_last_value_for_at_most_2_minutes() -> None:
    s = _s()
    day = date(2026, 6, 10)
    per = {_utc(10, 0, day): 100.0, _utc(10, 20, day): 90.0}
    out = hp.carry_forward(per, day, s)
    assert [m.minute for m in sorted(out) if m.hour == 10 and m.minute < 20] == [0, 1, 2]
    assert out[_utc(10, 2, day)] == 100.0 and _utc(10, 3, day) not in out  # 3 minutes later: no
    assert out[_utc(10, 20, day)] == 90.0 and out[_utc(10, 22, day)] == 90.0
    assert _utc(10, 23, day) not in out


def test_the_carry_stops_at_the_next_sample() -> None:
    s = _s()
    day = date(2026, 6, 10)
    out = hp.carry_forward({_utc(10, 0, day): 100.0, _utc(10, 2, day): 60.0}, day, s)
    assert out[_utc(10, 1, day)] == 100.0 and out[_utc(10, 2, day)] == 60.0
    assert out[_utc(10, 3, day)] == 60.0  # now the later sample is the one carried
    assert out[_utc(10, 4, day)] == 60.0 and _utc(10, 5, day) not in out


# --------------------------------------------------------------------------- cadence (pure)


def _steps(start: datetime, minutes: int, n: float, src: str) -> Row:
    return Row(start.date(), start, start + timedelta(minutes=minutes), src, {"value": n})


def test_cadence_spreads_a_record_evenly_over_its_minutes() -> None:
    out = hp.cadence_per_minute([_steps(_utc(9), 15, 1500, "fit")], [])
    assert len(out) == 15 and all(v == pytest.approx(100) for v in out.values())


def test_the_same_walk_from_two_sources_is_not_counted_twice() -> None:
    both = [_steps(_utc(9), 15, 1500, "fit"), _steps(_utc(9), 15, 1500, "withings")]
    out = hp.cadence_per_minute(both, [])
    assert sum(out.values()) == pytest.approx(1500)  # not 3000
    assert all(v == pytest.approx(100) for v in out.values())  # and so not 200 steps/min


def test_the_configured_source_wins_on_an_overlap() -> None:
    rows_ = [_steps(_utc(9), 10, 1000, "fit"), _steps(_utc(9), 10, 2000, "withings")]
    assert sum(hp.cadence_per_minute(rows_, ["fit"]).values()) == pytest.approx(1000)
    assert sum(hp.cadence_per_minute(rows_, ["withings"]).values()) == pytest.approx(2000)


def test_a_partial_overlap_keeps_the_total_steps_of_the_union() -> None:
    a = _steps(_utc(9, 0), 10, 1000, "fit")
    b = _steps(_utc(9, 5), 10, 1000, "withings")  # half of it overlaps `a`
    assert sum(hp.cadence_per_minute([a, b], ["fit"]).values()) == pytest.approx(1500)


def test_records_longer_than_an_hour_are_totals_not_cadence() -> None:
    total = _steps(_utc(0), 120, 12000, "fit")
    walk = _steps(_utc(9), 10, 1000, "withings")
    out = hp.cadence_per_minute([total, walk], ["fit"])
    assert sum(out.values()) == pytest.approx(1000)  # the total neither counts nor hides the walk
    assert hp.cadence_per_minute([_steps(_utc(9), 60, 6000, "fit")], [])  # exactly 60 min is kept
    assert not hp.cadence_per_minute([_steps(_utc(9), 61, 6100, "fit")], [])


def test_score_day_takes_the_maximum_per_minute() -> None:
    m0, m1, m2 = _utc(9, 0), _utc(9, 1), _utc(9, 2)
    hr = {m0: 100.0, m1: 140.0}  # HRmax 200: 50% -> 1, 70% -> 2
    cad = {m0: 100.0, m1: 100.0, m2: 130.0}
    r = hp.score_day(hr, cad, 200)
    assert (r.total, r.hr_points, r.cadence_points, r.active_minutes) == (1 + 2 + 2, 3, 4, 3)


def _only_hr(hr: float, hr_max: int = 200, **kw: object) -> hp.DayPoints:
    m = _utc(9)
    return hp.score_day({m: hr}, kw.get("cad", {}), hr_max, kw.get("sess", set()))  # type: ignore[arg-type]


def test_a_high_heart_rate_without_steps_or_session_earns_nothing() -> None:
    r = _only_hr(150.0)  # 75% of 200: vigorous, but standing still
    assert (r.total, r.hr_points, r.minutes_active) == (0, 0, 0)
    assert r.hr_points_ungated == 2  # what it WOULD have given: kept for the diagnostics


def test_sixty_steps_make_the_minute_active_for_the_heart_rate() -> None:
    m = _utc(9)
    r = _only_hr(150.0, cad={m: 60.0})  # 60 steps: not a cadence point (needs 100), but active
    assert (r.total, r.hr_points, r.cadence_points) == (2, 2, 0)
    assert (r.minutes_by_steps, r.minutes_by_session, r.minutes_active) == (1, 0, 1)
    assert (r.points_by_hr, r.points_by_cadence) == (2, 0)
    below = _only_hr(150.0, cad={m: 59.9})
    assert (below.total, below.minutes_active) == (0, 0)  # 59.9 steps: not active


def test_a_minute_inside_a_session_is_active_even_with_zero_steps() -> None:
    m = _utc(9)
    r = _only_hr(150.0, sess={m})  # cycling, gym: no steps at all
    assert (r.total, r.hr_points) == (2, 2)
    assert (r.minutes_by_session, r.minutes_by_steps, r.minutes_active) == (1, 0, 1)
    outside = _only_hr(150.0, sess={_utc(9, 1)})  # the session is the next minute
    assert outside.total == 0


def test_cadence_points_never_need_the_gate_and_the_max_still_applies() -> None:
    m = _utc(9)
    r = _only_hr(110.0, cad={m: 130.0})  # HR 55% -> 1, cadence 2: the cadence decides
    assert (r.total, r.points_by_cadence, r.points_by_hr) == (2, 2, 0)
    assert (r.hr_points, r.cadence_points) == (1, 2)


def test_minutes_active_counts_each_minute_once_when_steps_and_session_overlap() -> None:
    m = _utc(9)
    r = hp.score_day({}, {m: 80.0}, 200, {m, _utc(9, 1)})
    assert (r.minutes_by_steps, r.minutes_by_session, r.minutes_active) == (1, 2, 2)


def test_the_signature_changes_with_the_rules_version(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _s(birth_year=1990)
    before = hp.config_signature(s)
    assert before == hp.config_signature(s)
    monkeypatch.setattr(hp, "RULES_VERSION", hp.RULES_VERSION + 1)
    assert hp.config_signature(s) != before
    assert "1990" not in hp.config_signature(s)


def test_without_hr_max_only_cadence_counts() -> None:
    r = hp.score_day({_utc(9): 190.0}, {_utc(9): 100.0}, None)
    assert (r.total, r.hr_points, r.cadence_points) == (1, 0, 1)


# --------------------------------------------------------------------------- end to end


def _hr(hc: str, samples: list[tuple[str, int]]) -> dict[str, object]:
    return record(
        "HeartRate",
        hc,
        samples[0][0],
        samples[-1][0],
        {"samples": [{"time": t, "value": v} for t, v in samples]},
    )


def _at(h: int, m: int, day: str = D, off: str = "+02:00") -> str:
    return f"{day}T{h:02d}:{m:02d}:00{off}"


def _active(hc: str, h: int, m: int, minutes: int, day: str = D) -> dict[str, object]:
    """60 steps a minute: no cadence points (needs 100), but the minutes are ACTIVE."""
    end = m + minutes
    return record(
        "Steps", hc, _at(h, m, day), _at(h + end // 60, end % 60, day), {"value": 60 * minutes}
    )


async def _sql(app: FastAPI, sql: str) -> None:
    async with app.state.sessionmaker() as s:
        await s.execute(text(sql))
        await s.commit()


async def _week(web: httpx.AsyncClient, day: str = D) -> dict:
    r = await web.get(f"/api/v1/heart/points/week?date={day}")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _day(week: dict, day: str = D) -> dict:
    return next(d for d in week["days"] if d["date"] == day)


async def test_hr_points_with_exact_thresholds_end_to_end(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    low, mod, high = hp_bpm(HR_MAX_1990)
    samples = (
        [(_at(10, m), low) for m in range(5)]  # 49.x% -> 0
        + [(_at(10, 5 + m), mod) for m in range(5)]  # exactly 50% -> 1
        + [(_at(10, 10 + m), mod_top(HR_MAX_1990)) for m in range(5)]  # 69.x% -> 1
        + [(_at(10, 15 + m), high) for m in range(5)]  # exactly 70% -> 2
        + [(_at(10, 20), 60)]  # ends the carry
    )
    await post_records(client, auth, [_hr("h1", samples), _active("s1", 10, 0, 21)])
    day = _day(await _week(web))
    assert day["points"] == 5 * (0 + 1 + 1 + 2)
    assert (day["hr_points"], day["cadence_points"]) == (20, 0)


def hp_bpm(hr_max: int) -> tuple[int, int, int]:
    """(just under 50%, exactly-or-just-over 50%, first integer >= 70%) for an HRmax."""
    half = -(-hr_max // 2)  # ceil
    seventy = -(-hr_max * 70 // 100)
    assert (half - 1) * 100 < 50 * hr_max <= half * 100
    return half - 1, half, seventy


def mod_top(hr_max: int) -> int:
    top = (hr_max * 70) // 100  # the largest integer bpm still under 70%
    if top * 100 >= 70 * hr_max:
        top -= 1
    return top


async def test_the_minute_is_the_max_of_hr_and_cadence_end_to_end(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, mod, _ = hp_bpm(HR_MAX_1990)
    hr = _hr("h1", [(_at(11, m), mod) for m in range(10)] + [(_at(11, 10), 60)])
    steps = record("Steps", "s1", _at(11, 0), _at(11, 10), {"value": 1000})  # 100 steps/min
    await post_records(client, auth, [hr, steps])
    day = _day(await _week(web))
    assert day["points"] == 10  # each minute is worth 1 (not 1 + 1)
    assert (day["hr_points"], day["cadence_points"]) == (10, 10)


async def test_the_last_value_carries_for_two_minutes_only(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, mod, _ = hp_bpm(HR_MAX_1990)
    await post_records(
        client, auth, [_hr("h1", [(_at(12, 0), mod), (_at(12, 30), 60)]), _active("s1", 12, 0, 10)]
    )
    day = _day(await _week(web))
    assert day["points"] == 3  # the sample minute and the 2 after it, then nothing until 12:30


async def test_a_walk_logged_by_two_apps_is_counted_once(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    fit = record("Steps", "fit1", _at(9, 0), _at(9, 15), {"value": 1500}, pkg="com.fit")
    withings = record("Steps", "wi1", _at(9, 0), _at(9, 15), {"value": 1500}, pkg="com.withings")
    await post_records(client, auth, [fit, withings])
    day = _day(await _week(web))
    assert day["points"] == 15 and day["cadence_points"] == 15  # 100 steps/min, not 200 (=> 30)


async def test_without_birth_year_only_the_cadence_counts_and_the_week_says_so(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    assert settings.birth_year is None and settings.hr_max is None
    hr = _hr("h1", [(_at(10, m), 170) for m in range(10)] + [(_at(10, 10), 60)])
    steps = record("Steps", "s1", _at(10, 0), _at(10, 10), {"value": 1300})  # 130/min -> 2
    await post_records(client, auth, [hr, steps])
    week = await _week(web)
    assert week["hr_configured"] is False
    day = _day(week)
    assert (day["hr_points"], day["cadence_points"], day["points"]) == (0, 20, 20)
    series = (await web.get(f"/api/v1/heart/points?from={D}&to={D}&bucket=week")).json()
    assert series["hr_configured"] is False
    rules = (await web.get("/api/v1/heart/points/rules")).json()
    assert rules["heart_rate"]["configured"] is False and rules["heart_rate"]["hr_max"] is None


async def test_the_hr_max_override_wins(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    settings.hr_max = 200
    # 130 bpm: 65% of 200 -> 1 point (with the 1990 birth year HRmax 181 it would be 71.8% -> 2)
    await post_records(
        client, auth, [_hr("h1", [(_at(10, 0), 130), (_at(10, 1), 60)]), _active("s1", 10, 0, 5)]
    )
    assert _day(await _week(web))["points"] == 1
    rules = (await web.get("/api/v1/heart/points/rules")).json()["heart_rate"]
    assert (rules["hr_max"], rules["hr_max_source"]) == (200, "override")


async def test_every_beat_counts_workouts_are_not_excluded(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, _, high = hp_bpm(HR_MAX_1990)
    run = record(
        "ExerciseSession",
        "run1",
        _at(18, 0),
        _at(18, 20),
        {"exercise_type": "RUNNING"},
        method="active",
    )
    walk = record(
        "ExerciseSession",
        "walk1",
        _at(8, 0),
        _at(8, 20),
        {"exercise_type": "WALKING"},
        method="active",
    )
    hr = _hr(
        "h1",
        [(_at(8, m), high) for m in range(20)]
        + [(_at(8, 20), 60)]
        + [(_at(18, m), high) for m in range(20)]
        + [(_at(18, 20), 60)],
    )
    await post_records(client, auth, [hr, run, walk])
    assert _day(await _week(web))["points"] == 20 * 2 * 2  # the run AND the walk, both counted


async def test_dst_change_day_counts_both_hours_of_the_repeated_02_30(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    day = "2026-10-25"  # clocks go back: 02:30 happens twice (+02:00 then +01:00)
    _, mod, _ = hp_bpm(HR_MAX_1990)
    samples = [
        (_at(2, 30, day, "+02:00"), mod),
        (_at(2, 31, day, "+02:00"), 60),
        (_at(2, 30, day, "+01:00"), mod),
        (_at(2, 31, day, "+01:00"), 60),
    ]
    await post_records(
        client,
        auth,
        [
            record(
                "HeartRate",
                "h1",
                samples[0][0],
                samples[1][0],
                {"samples": [{"time": t, "value": v} for t, v in samples[:2]]},
            ),
            record(
                "HeartRate",
                "h2",
                samples[2][0],
                samples[3][0],
                {"samples": [{"time": t, "value": v} for t, v in samples[2:]]},
                offset=3600,
            ),
            record(  # a session across the repeated hour makes both minutes active
                "ExerciseSession",
                "dst",
                _at(2, 0, day, "+02:00"),
                _at(2, 45, day, "+01:00"),
                {"exercise_type": "RUNNING"},
                method="active",
            ),
        ],
    )
    assert _day(await _week(web, day), day)["points"] == 2


async def test_the_week_is_monday_to_sunday(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    # Sunday 2026-10-25 and Monday 2026-10-26: two different weeks
    for day, hc in (("2026-10-25", "a"), ("2026-10-26", "b")):
        _, mod, _ = hp_bpm(HR_MAX_1990)
        await post_records(
            client,
            auth,
            [
                _hr(hc, [(_at(10, 0, day), mod), (_at(10, 6, day), 60)]),
                _active(f"s{hc}", 10, 0, 10, day),
            ],
        )
    week1 = await _week(web, "2026-10-25")
    week2 = await _week(web, "2026-10-26")
    assert (week1["week_start"], week1["week_end"]) == ("2026-10-19", "2026-10-25")
    assert (week2["week_start"], week2["week_end"]) == ("2026-10-26", "2026-11-01")
    assert week1["total"] == 3 and week2["total"] == 3  # the sample minute + 2 carried
    assert next(d["date"] for d in week1["days"]) == "2026-10-19" and len(week1["days"]) == 7
    series = (
        await web.get("/api/v1/heart/points?from=2026-10-19&to=2026-11-01&bucket=week")
    ).json()
    assert [(p["t"], p["v"]) for p in series["points"]] == [("2026-10-19", 3), ("2026-10-26", 3)]


async def test_week_card_values(web: httpx.AsyncClient, app: FastAPI, settings: Settings) -> None:
    today = TODAY
    monday = today - timedelta(days=today.weekday())
    async with app.state.sessionmaker() as s:
        from app.models import DailyMetric

        for i, v in ((0, 60.0), (1, 40.0)):
            s.add(
                DailyMetric(
                    local_date=monday + timedelta(days=i),
                    type="HeartPoints",
                    source="computed",
                    sum_value=v,
                    count=1,
                    unit="points",
                    detail={"hr_points": 1, "cadence_points": 2},
                )
            )
        await s.commit()
    w = (await web.get("/api/v1/heart/points/week")).json()
    assert w["is_current"] is True and w["goal"] == 150 and w["total"] == 100
    assert w["remaining"] == 50 and w["reached"] is False
    assert w["days_left"] == (monday + timedelta(days=6) - today).days + 1  # today included
    past = (await web.get(f"/api/v1/heart/points/week?date={(monday - timedelta(days=3))}")).json()
    assert past["is_current"] is False and past["days_left"] == 0 and past["total"] == 0


async def test_weeks_over_the_goal_and_the_other_buckets(
    web: httpx.AsyncClient, app: FastAPI
) -> None:
    start = TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=4)  # a Monday, 4 weeks back
    async with app.state.sessionmaker() as s:
        from app.models import DailyMetric

        for week, per_day in enumerate((30.0, 10.0, 25.0, 5.0)):  # 210, 70, 175, 35 points
            for i in range(7):
                s.add(
                    DailyMetric(
                        local_date=start + timedelta(weeks=week, days=i),
                        type="HeartPoints",
                        source="computed",
                        sum_value=per_day,
                        count=1,
                        unit="points",
                        detail={},
                    )
                )
        await s.commit()
    last = start + timedelta(weeks=4) - timedelta(days=1)
    r = (await web.get(f"/api/v1/heart/points?from={start}&to={last}&bucket=week")).json()
    assert [p["v"] for p in r["points"]] == [210, 70, 175, 35] and r["weekly_goal"] == 150
    assert all(p["complete"] for p in r["points"])
    assert r["summary"]["total"] == 490 and r["summary"]["weeks_over_goal"] == 2
    assert r["summary"]["buckets_complete"] == 4 and r["previous_summary"]["total"] == 0
    month = (await web.get(f"/api/v1/heart/points?from={start}&to={last}&bucket=month")).json()
    assert (
        sum(p["v"] for p in month["points"]) == 490 and month["summary"]["weeks_over_goal"] is None
    )
    year = (await web.get(f"/api/v1/heart/points?from={start}&to={last}&bucket=year")).json()
    assert sum(p["v"] for p in year["points"]) == 490 and len(year["points"]) in (1, 2)
    # the running week is never "complete": it is still being earned
    now = (
        await web.get(
            f"/api/v1/heart/points?from={last + timedelta(days=1)}&to={TODAY}&bucket=week"
        )
    ).json()
    assert all(not p["complete"] for p in now["points"])


async def test_series_validation(web: httpx.AsyncClient) -> None:
    assert (await web.get("/api/v1/heart/points?bucket=hour")).status_code == 422
    r = await web.get("/api/v1/heart/points?from=2026-10-10&to=2026-10-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_range"
    empty = (await web.get("/api/v1/heart/points")).json()
    assert empty["summary"]["total"] == 0 and empty["weekly_goal"] == 150


async def test_points_follow_ingest_updates_and_deletions(
    web: httpx.AsyncClient,
    client: httpx.AsyncClient,
    auth: dict[str, str],
    settings: Settings,
    app: FastAPI,
) -> None:
    settings.birth_year = 1990
    _, mod, _ = hp_bpm(HR_MAX_1990)
    await post_records(
        client, auth, [_hr("h1", [(_at(10, 0), mod), (_at(10, 1), 60)]), _active("s1", 10, 0, 10)]
    )
    assert _day(await _week(web))["points"] == 1
    await post_records(
        client,
        auth,
        [
            {
                **_hr("h1", [(_at(10, 0), mod), (_at(10, 1), mod), (_at(10, 2), 60)]),
                "last_modified": "2026-10-15T09:00:00Z",
            }
        ],
    )
    assert _day(await _week(web))["points"] == 2
    r = await post(
        client,
        auth,
        "deletions",
        {
            "device_id": DEVICE,
            "sync_id": "1f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a31",
            "items": [{"hc_id": "h1"}, {"hc_id": "s1"}],
        },
    )
    assert r.status_code == 200
    assert _day(await _week(web))["points"] is None  # no data left: no row
    assert await scalar(app, "SELECT count(*) FROM daily_metric WHERE type='HeartPoints'") == 0


async def test_recompute_after_changing_the_settings_and_only_missing_at_startup(
    web: httpx.AsyncClient,
    client: httpx.AsyncClient,
    auth: dict[str, str],
    settings: Settings,
    app: FastAPI,
) -> None:
    settings.birth_year = 1990
    await post_records(
        client, auth, [_hr("h1", [(_at(10, 0), 130), (_at(10, 1), 60)]), _active("s1", 10, 0, 5)]
    )  # 130 bpm
    assert _day(await _week(web))["points"] == 2  # 71.8% of 181
    async with app.state.sessionmaker() as s:
        assert await hp.days_to_compute(s, settings) == []  # up to date
    settings.hr_max = 200  # the user changes the setting: 130 bpm is now 65%
    async with app.state.sessionmaker() as s:
        assert await hp.days_to_compute(s, settings) == [DAY]  # stale: computed with other settings
        assert await maintenance.recompute_heart_points(s, settings, only_missing=True) == 1
        assert await maintenance.recompute_heart_points(s, settings, only_missing=True) == 0
    assert _day(await _week(web))["points"] == 1
    # the whole history, on demand (first deploy / the CLI command)
    async with app.state.sessionmaker() as s:
        assert await maintenance.recompute_heart_points(s, settings) == 1
        assert await maintenance.recompute_heart_points(s, settings, first=TODAY, last=TODAY) == 0
    # a missing row is rebuilt at startup
    await _sql(app, "DELETE FROM daily_metric WHERE type='HeartPoints'")
    async with app.state.sessionmaker() as s:
        assert await maintenance.recompute_heart_points(s, settings, only_missing=True) == 1
    assert _day(await _week(web))["points"] == 1


async def test_the_nightly_recompute_includes_heart_points(
    web: httpx.AsyncClient,
    client: httpx.AsyncClient,
    auth: dict[str, str],
    settings: Settings,
    app: FastAPI,
) -> None:
    settings.birth_year = 1990
    await post_records(
        client, auth, [_hr("h1", [(_at(10, 0), 130), (_at(10, 1), 60)]), _active("s1", 10, 0, 5)]
    )
    await _sql(app, "DELETE FROM daily_metric WHERE type='HeartPoints'")
    async with app.state.sessionmaker() as s:
        await maintenance.recompute_range(s, settings, DAY, DAY)
    assert _day(await _week(web))["points"] == 2


async def test_rules_endpoint_comes_from_the_constants_and_hides_the_birth_year(
    web: httpx.AsyncClient, settings: Settings
) -> None:
    settings.birth_year = 1990
    r = await web.get("/api/v1/heart/points/rules")
    assert r.status_code == 200
    body = r.json()
    assert body == points_api.describe_points_rules(settings)
    hr = body["heart_rate"]
    assert (hr["moderate_pct"], hr["vigorous_pct"], hr["carry_max_minutes"]) == (50, 70, 2)
    assert hr["configured"] is True and hr["hr_max_source"] == "birth_year"
    assert hr["hr_max"] == int(205.8 - 0.685 * (TODAY.year - 1990) + 0.5)
    assert hr["formula"] == {"intercept": 205.8, "slope": 0.685} and hr["needs_active_minute"]
    assert body["active_minute"] == {"min_steps": 60, "exercise_session": True}
    assert body["rules_version"] == hp.RULES_VERSION
    assert body["cadence"] == {
        "moderate_steps": 100,
        "vigorous_steps": 130,
        "max_record_minutes": 60,
    }
    assert body["points"] == {"moderate": 1, "vigorous": 2} and body["combine"] == "max"
    assert body["met_used"] is False and body["weekly_goal"] == 150
    assert "1990" not in r.text  # the birth year itself never leaves the server


async def test_heart_points_endpoints_need_a_session(client: httpx.AsyncClient) -> None:
    for path in ("/api/v1/heart/points", "/api/v1/heart/points/week", "/api/v1/heart/points/rules"):
        assert (await client.get(path)).status_code == 401


async def test_the_seed_has_runs_fast_walks_and_weeks_above_and_below_the_goal(
    app: FastAPI, settings: Settings, web: httpx.AsyncClient
) -> None:
    from app.seed.loader import load_synthetic
    from app.seed.synthetic import SeedConfig, generate

    settings.birth_year = 1990  # fictitious
    cfg = SeedConfig(days=84, seed=5, end_date=TODAY, hr_interval_min=5, rest_weeks=True)
    await load_synthetic(app.state.sessionmaker, settings, generate(cfg))
    first = TODAY - timedelta(days=83)
    r = (await web.get(f"/api/v1/heart/points?from={first}&to={TODAY}&bucket=week")).json()
    weekly = [p["v"] for p in r["points"] if p["complete"]]
    assert len(weekly) >= 10
    assert any(v >= 150 for v in weekly) and any(v < 150 for v in weekly), weekly
    # runs are worth 2 points a minute (HR), fast walks 1 (cadence 112 steps/min)
    rows_ = await rows(
        app,
        "SELECT (detail->>'hr_points')::int, (detail->>'cadence_points')::int "
        "FROM daily_metric WHERE type='HeartPoints'",
    )
    assert any(hr_p >= 40 for hr_p, _ in rows_)
    assert any(cad >= 20 for _, cad in rows_)


async def _seed_days(app: FastAPI, first: date, values: list[float]) -> None:
    from app.models import DailyMetric

    async with app.state.sessionmaker() as s:
        for i, v in enumerate(values):
            s.add(
                DailyMetric(
                    local_date=first + timedelta(days=i),
                    type="HeartPoints",
                    source="computed",
                    sum_value=v,
                    count=1,
                    unit="points",
                    detail={},
                )
            )
        await s.commit()


async def test_day_bucket_and_the_indicative_reference(
    web: httpx.AsyncClient, app: FastAPI
) -> None:
    first = TODAY - timedelta(days=10)
    # 21 sits just under 150/7 = 21.43, 22 just over
    values = [0.0, 21.0, 22.0, 50.0, 21.0, 30.0, 22.0, 5.0, 100.0, 21.0]
    await _seed_days(app, first, values)
    last = TODAY - timedelta(days=1)
    r = (await web.get(f"/api/v1/heart/points?from={first}&to={last}&bucket=day")).json()
    assert r["bucket"] == "day" and r["coarsened"] is False
    assert [p["v"] for p in r["points"]] == values and len(r["points"]) == 10
    assert next(p["t"] for p in r["points"]) == first.isoformat()
    assert r["daily_reference"] == pytest.approx(150 / 7)  # from WEEKLY_GOAL, not a typed number
    assert r["weekly_goal"] == 150
    assert all(p["complete"] for p in r["points"])
    # 22, 50, 30, 22, 100 are at or above 21.43; 0, 21, 21, 5, 21 are not
    assert r["summary"]["days_over_reference"] == 5 and r["summary"]["buckets_complete"] == 10
    assert r["summary"]["weeks_over_goal"] is None and r["summary"]["total"] == sum(values)
    # today is partial: never counted as a complete day
    now = (await web.get(f"/api/v1/heart/points?from={last}&to={TODAY}&bucket=day")).json()
    assert [p["complete"] for p in now["points"]] == [True, False]
    # the other buckets carry no day reference
    week = (await web.get(f"/api/v1/heart/points?from={first}&to={last}&bucket=week")).json()
    assert week["summary"]["days_over_reference"] is None and week["coarsened"] is False
    assert week["daily_reference"] == pytest.approx(150 / 7)


async def test_day_bucket_widens_to_week_beyond_the_chart_point_limit(
    web: httpx.AsyncClient,
) -> None:
    from app.services.queries import MAX_POINTS

    last = TODAY
    ok_first = last - timedelta(days=MAX_POINTS - 1)  # exactly MAX_POINTS days: still per day
    ok = (await web.get(f"/api/v1/heart/points?from={ok_first}&to={last}&bucket=day")).json()
    assert ok["bucket"] == "day" and ok["coarsened"] is False and len(ok["points"]) == MAX_POINTS
    wide_first = last - timedelta(days=MAX_POINTS)  # one more: the bucket widens, and says so
    wide = (await web.get(f"/api/v1/heart/points?from={wide_first}&to={last}&bucket=day")).json()
    assert wide["bucket"] == "week" and wide["coarsened"] is True
    assert len(wide["points"]) <= MAX_POINTS // 7 + 2
    assert wide["summary"]["days_over_reference"] is None
    # asking for a week never reports "coarsened"
    asked = (await web.get(f"/api/v1/heart/points?from={wide_first}&to={last}&bucket=week")).json()
    assert asked["bucket"] == "week" and asked["coarsened"] is False


async def test_rules_include_the_daily_reference(web: httpx.AsyncClient) -> None:
    body = (await web.get("/api/v1/heart/points/rules")).json()
    assert body["daily_reference"] == pytest.approx(body["weekly_goal"] / 7)


# --------------------------------------------------------------------------- active-minute gate


async def test_high_hr_standing_still_earns_nothing_but_is_kept_in_the_detail(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, _, high = hp_bpm(HR_MAX_1990)
    # an hour at 70%+ with no steps and no session (stress, a coffee): no points
    hr = _hr("h1", [(_at(15, m), high) for m in range(60)] + [(_at(16, 0), 60)])
    await post_records(client, auth, [hr])
    day = _day(await _week(web))
    assert day["points"] == 0 and day["hr_points"] == 0
    assert day["detail"]["hr_points_ungated"] == 120 and day["detail"]["minutes_active"] == 0


async def test_a_cycling_session_without_steps_earns_the_heart_rate_points(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, _, high = hp_bpm(HR_MAX_1990)
    ride = record(
        "ExerciseSession",
        "ride",
        _at(17, 0),
        _at(17, 30),
        {"exercise_type": "BIKING_STATIONARY"},
        method="manual",  # even an automatic or manual session of any type counts
    )
    hr = _hr("h1", [(_at(17, m), high) for m in range(40)] + [(_at(17, 45), 60)])
    await post_records(client, auth, [ride, hr])
    day = _day(await _week(web))
    assert day["points"] == 30 * 2  # only the 30 minutes of the session, the rest is outside it
    d = day["detail"]
    assert (d["minutes_by_session"], d["minutes_by_steps"], d["minutes_active"]) == (30, 0, 30)
    assert (d["points_by_hr"], d["points_by_cadence"]) == (60, 0)
    assert d["hr_points_ungated"] > d["hr_points"]  # the ten minutes after it were not active


async def test_a_deleted_session_does_not_activate_the_minutes(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, _, high = hp_bpm(HR_MAX_1990)
    ride = record("ExerciseSession", "ride", _at(17, 0), _at(17, 30), {"exercise_type": "BIKING"})
    hr = _hr("h1", [(_at(17, m), high) for m in range(10)] + [(_at(17, 10), 60)])
    await post_records(client, auth, [ride, hr])
    assert _day(await _week(web))["points"] == 20
    body = {
        "device_id": DEVICE,
        "sync_id": "1f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a32",
        "items": [{"hc_id": "ride"}],
    }
    assert (await post(client, auth, "deletions", body)).status_code == 200
    assert _day(await _week(web))["points"] == 0


async def test_the_detail_is_summed_per_bucket_and_matches_the_days(
    web: httpx.AsyncClient, client: httpx.AsyncClient, auth: dict[str, str], settings: Settings
) -> None:
    settings.birth_year = 1990
    _, _, high = hp_bpm(HR_MAX_1990)
    steps = record("Steps", "s1", _at(9, 0), _at(9, 10), {"value": 1300})  # 130/min: 2 each
    hr = _hr("h1", [(_at(9, m), high) for m in range(10)] + [(_at(9, 10), 60)])
    await post_records(client, auth, [steps, hr])
    day = (await web.get(f"/api/v1/heart/points?from={D}&to={D}&bucket=day")).json()["points"][0]
    week = (await web.get(f"/api/v1/heart/points?from={D}&to={D}&bucket=week")).json()["points"][0]
    assert day["v"] == 20 and day["detail"] == week["detail"]
    assert day["detail"]["minutes_by_steps"] == 10 and day["detail"]["cadence_points"] == 20
    assert day["detail"]["points_by_hr"] == 20  # hr 2 == cadence 2: the heart rate "decided" (>=)


async def test_changing_the_rules_version_recomputes_everything_in_the_background(
    web: httpx.AsyncClient,
    client: httpx.AsyncClient,
    auth: dict[str, str],
    settings: Settings,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.birth_year = 1990
    await post_records(
        client, auth, [_hr("h1", [(_at(10, 0), 130), (_at(10, 1), 60)]), _active("s1", 10, 0, 5)]
    )
    async with app.state.sessionmaker() as s:
        assert await hp.days_to_compute(s, settings) == []
    # an old row (written by a previous rules version, no "rules" marker, other signature)
    await _sql(
        app,
        'UPDATE daily_metric SET detail = detail || \'{"config": "old"}\' '
        "WHERE type='HeartPoints'",
    )
    async with app.state.sessionmaker() as s:
        assert await hp.days_to_compute(s, settings) == [DAY]
        assert await maintenance.recompute_heart_points(s, settings, only_missing=True) == 1
        assert await hp.days_to_compute(s, settings) == []
    monkeypatch.setattr(hp, "RULES_VERSION", hp.RULES_VERSION + 1)  # the next release
    async with app.state.sessionmaker() as s:
        assert await hp.days_to_compute(s, settings) == [DAY]
        assert await maintenance.recompute_heart_points(s, settings, only_missing=True) == 1


async def test_the_seed_stress_days_have_high_heart_rate_at_rest_and_no_points_for_it(
    app: FastAPI, settings: Settings
) -> None:
    from app.seed.loader import load_synthetic
    from app.seed.synthetic import SeedConfig, generate

    settings.birth_year = 1990  # fictitious
    cfg = SeedConfig(days=28, seed=5, end_date=TODAY, hr_interval_min=5, stress_days=True)
    await load_synthetic(app.state.sessionmaker, settings, generate(cfg))
    rows_ = await rows(
        app,
        "SELECT local_date, (detail->>'hr_points_ungated')::int, (detail->>'hr_points')::int, "
        "(detail->>'minutes_by_session')::int FROM daily_metric WHERE type='HeartPoints' "
        "AND extract(isodow FROM local_date) = 3",
    )
    stress = [(u, g, s_) for _, u, g, s_ in rows_ if u >= 50 and not s_]  # no session that day
    assert stress, rows_  # Wednesdays with 50 minutes of high heart rate at rest ...
    assert all(g == 0 for _, g, _ in stress)  # ... which earned nothing from the heart rate
