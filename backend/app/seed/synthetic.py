"""Deterministic SYNTHETIC health data in the exact shape of the ingest API (contract v1).

Nothing here is derived from real data. Sources are fake packages (``synthetic.*``) and the
exercise route sits around (0 N, 0 E) so it cannot be mistaken for a real place.

Two sources deliberately record overlapping data (steps, sleep, weight, workouts), because that is
the situation the writer's de-duplication has to survive with Fit + Feelfit + Withings.
"""

from __future__ import annotations

import math
import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

NAMESPACE = uuid.UUID("5b2c8f0e-0000-4000-8000-5ba0517e71c5")
PHONE = "synthetic.phone"
WATCH = "synthetic.watch"
SCALE = "synthetic.scale"
SEED_DEVICE_ID = uuid.uuid5(NAMESPACE, "device")


@dataclass(frozen=True)
class SeedConfig:
    days: int = 30
    seed: int = 42
    end_date: date | None = None  # last generated local day (default: today)
    tz: str = "Europe/Rome"
    hr_interval_min: int = 5


@dataclass
class SyntheticData:
    records: list[dict[str, Any]]
    aggregates: list[dict[str, Any]]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _offset_s(dt: datetime) -> int:
    off = dt.utcoffset()
    assert off is not None
    return int(off.total_seconds())


class _Builder:
    def __init__(self, cfg: SeedConfig) -> None:
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.tz)
        self.rng = random.Random(cfg.seed)
        self.records: list[dict[str, Any]] = []

    def add(
        self,
        type_: str,
        source: str,
        start: datetime,
        end: datetime | None,
        data: dict[str, Any],
        *,
        method: str = "automatic",
    ) -> None:
        rec: dict[str, Any] = {
            "type": type_,
            "hc_id": str(uuid.uuid5(NAMESPACE, f"{type_}|{source}|{start.isoformat()}")),
            "start_time": _iso(start),
            "start_offset_s": _offset_s(start),
            "source": {
                "package": source,
                "device": {"type": "WATCH" if source == WATCH else "PHONE", "model": "SynthModel"},
                "recording_method": method,
            },
            "last_modified": _iso((end or start).astimezone(UTC) + timedelta(minutes=1)),
            "data": data,
        }
        if end is not None:
            rec["end_time"] = _iso(end)
            rec["end_offset_s"] = _offset_s(end)
        self.records.append(rec)

    def at(self, day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), tzinfo=self.tz)

    # ----------------------------------------------------------------- per-day generators

    def steps_and_energy(self, day: date) -> None:
        rng = self.rng
        weekend = day.weekday() >= 5
        for hour in range(7, 23):
            for quarter in range(4):
                start = self.at(day, hour, quarter * 15)
                end = start + timedelta(minutes=15)
                busy = rng.random() < (0.45 if weekend else 0.6)
                steps = int(rng.gauss(260, 120)) if busy else int(rng.uniform(0, 30))
                steps = max(steps, 0)
                for source, factor, present in (
                    (PHONE, 1.0, True),
                    (WATCH, rng.uniform(0.9, 1.1), rng.random() < 0.9),
                ):
                    if not present:
                        continue
                    n = int(steps * factor)
                    self.add("Steps", source, start, end, {"value": n})
                    self.add("Distance", source, start, end, {"value": round(n * 0.74, 1)})
        for hour in range(24):
            start, end = self.at(day, hour), self.at(day, hour) + timedelta(hours=1)
            active = max(0.0, rng.gauss(18, 10)) if 7 <= hour < 23 else 0.0
            self.add("ActiveCaloriesBurned", WATCH, start, end, {"value": round(active, 1)})
            self.add("TotalCaloriesBurned", WATCH, start, end, {"value": round(70 + active, 1)})

    def heart(self, day: date) -> None:
        rng = self.rng
        step = self.cfg.hr_interval_min
        for hour in range(24):
            start = self.at(day, hour)
            end = start + timedelta(hours=1)
            base = 54 if hour < 6 else 72 + 6 * math.sin((hour - 6) / 16 * math.pi)
            samples = []
            for minute in range(0, 60, step):
                bpm = round(base + rng.gauss(0, 4) + (35 if rng.random() < 0.02 else 0))
                samples.append(
                    {
                        "time": _iso(start + timedelta(minutes=minute)),
                        "value": max(40, min(bpm, 190)),
                    }
                )
            self.add("HeartRate", WATCH, start, end, {"samples": samples})

    def night(self, day: date) -> None:
        """Sleep that ends on ``day`` morning (attributed to ``day``), plus night vitals."""
        rng = self.rng
        bedtime = datetime.combine(
            day - timedelta(days=1), time(23, 0), tzinfo=self.tz
        ) + timedelta(minutes=rng.randint(-30, 60))
        wake = self.at(day, 6, 30) + timedelta(minutes=rng.randint(-20, 40))
        stages = []
        t = bedtime
        cycle = ["light", "deep", "light", "rem"]
        i = 0
        while t < wake:
            length = timedelta(minutes=rng.randint(15, 50))
            stage = "awake" if rng.random() < 0.05 else cycle[i % len(cycle)]
            end = min(t + length, wake)
            stages.append({"stage": stage, "start_time": _iso(t), "end_time": _iso(end)})
            t = end
            i += 1
        self.add("SleepSession", WATCH, bedtime, wake, {"title": "Night", "stages": stages})
        # the phone also logs "something" for the same night, without stages and slightly shifted
        self.add(
            "SleepSession", PHONE, bedtime + timedelta(minutes=5), wake - timedelta(minutes=3), {}
        )
        mid = bedtime + (wake - bedtime) / 2
        self.add("OxygenSaturation", WATCH, mid, None, {"value": round(rng.uniform(94, 99), 1)})
        self.add(
            "HeartRateVariabilityRmssd", WATCH, mid, None, {"value": round(rng.gauss(48, 9), 1)}
        )
        self.add(
            "RestingHeartRate", WATCH, self.at(day, 7), None, {"value": round(rng.gauss(57, 2))}
        )

    def weight(self, day: date, index: int) -> None:
        if index % 2:
            return
        w = round(78.0 - index * 0.02 + self.rng.gauss(0, 0.3), 1)
        when = self.at(day, 7, 10)
        self.add("Weight", SCALE, when, None, {"value": w}, method="manual")
        self.add("Weight", PHONE, when, None, {"value": w}, method="manual")  # mirrored copy

    # (exercise_type, HC constant, title, minutes range, has GPS route)
    WORKOUTS = (
        ("WALKING", 79, "Evening walk", (30, 55), True),
        ("RUNNING", 56, "Easy run", (25, 45), True),
        ("BIKING", 8, "Ride", (40, 75), False),
    )

    def workout(self, day: date, index: int) -> None:
        """Roughly every other day, rotating walk / run / ride, each logged by watch AND phone."""
        if index % 2:
            return
        rng = self.rng
        kind, type_id, title, (lo, hi), has_route = self.WORKOUTS[(index // 2) % len(self.WORKOUTS)]
        start = self.at(day, 18, rng.randint(0, 30))
        minutes = rng.randint(lo, hi)
        end = start + timedelta(minutes=minutes)
        data: dict[str, Any] = {"exercise_type": kind, "exercise_type_id": type_id, "title": title}
        if has_route:
            lat, lon = 0.0, 0.0  # (0 N, 0 E): obviously not a real place
            route = []
            for k in range(0, minutes + 1, 2):
                lat += rng.gauss(0.00005, 0.00002)
                lon += rng.gauss(0.00005, 0.00002)
                route.append(
                    {
                        "time": _iso(start + timedelta(minutes=k)),
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                        "alt_m": round(10 + rng.gauss(0, 1), 1),
                    }
                )
            data["route"] = route
        self.add("ExerciseSession", WATCH, start, end, data, method="active")
        # the phone logs the same workout without the route
        self.add(
            "ExerciseSession",
            PHONE,
            start,
            end,
            {"exercise_type": kind, "exercise_type_id": type_id},
            method="active",
        )

    def blood_pressure(self, day: date, index: int) -> None:
        """A morning and an evening reading every third day (manual entries)."""
        if index % 3:
            return
        rng = self.rng
        for hour, minute in ((7, 30), (20, 40)):
            data = {
                "systolic": round(rng.gauss(119, 7)),
                "diastolic": round(rng.gauss(77, 5)),
                "body_position": "SITTING_DOWN",
            }
            self.add(
                "BloodPressure", WATCH, self.at(day, hour, minute), None, data, method="manual"
            )

    # ----------------------------------------------------------------- official aggregates

    def official_aggregates(self, days: list[date]) -> list[dict[str, Any]]:
        """What HC's aggregate() would say: one source of truth per day, no double counting."""
        out: list[dict[str, Any]] = []
        for day in days:
            midnight = self.at(day, 0)
            snap = _iso((midnight + timedelta(days=1)).astimezone(UTC))
            steps = sum(
                r["data"]["value"]
                for r in self.records
                if r["type"] == "Steps"
                and r["source"]["package"] == PHONE
                and r["start_time"].startswith(day.isoformat())
            )
            hr = [
                s["value"]
                for r in self.records
                if r["type"] == "HeartRate" and r["start_time"].startswith(day.isoformat())
                for s in r["data"]["samples"]
            ]
            out.append(
                {
                    "date": day.isoformat(),
                    "type": "Steps",
                    "sum": steps,
                    "data_origins": [PHONE],
                    "snapshot_at": snap,
                }
            )
            if hr:
                out.append(
                    {
                        "date": day.isoformat(),
                        "type": "HeartRate",
                        "avg": round(sum(hr) / len(hr), 2),
                        "min": min(hr),
                        "max": max(hr),
                        "count": len(hr),
                        "data_origins": [WATCH],
                        "snapshot_at": snap,
                    }
                )
        return out


def generate(cfg: SeedConfig | None = None) -> SyntheticData:
    cfg = cfg or SeedConfig()
    builder = _Builder(cfg)
    end = cfg.end_date or datetime.now(builder.tz).date()
    days = [end - timedelta(days=n) for n in range(cfg.days - 1, -1, -1)]
    for index, day in enumerate(days):
        builder.steps_and_energy(day)
        builder.heart(day)
        builder.night(day)
        builder.weight(day, index)
        builder.workout(day, index)
        builder.blood_pressure(day, index)
    return SyntheticData(builder.records, builder.official_aggregates(days))


def chunked(items: list[dict[str, Any]], size: int = 500) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
