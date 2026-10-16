"""Registry of the Health Connect record types accepted by the ingest API.

Every supported type declares:
  * its *shape* (how it sits on the time axis),
  * how it rolls up into ``daily_metric`` (``daily`` kind),
  * a pydantic model validating the type-specific ``data`` payload.

Adding a type is a single ``_register`` call. The contract document
(docs/api-contract.md) lists the same types; a test keeps the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, create_model

Shortstr = Annotated[str, Field(min_length=1, max_length=64)]
Title = Annotated[str, Field(max_length=200)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class Shape(StrEnum):
    INSTANT = "instant"  # one point in time; end_time optional
    INTERVAL = "interval"  # cumulative value over [start, end]
    SERIES = "series"  # [start, end] containing timestamped samples
    SESSION = "session"  # [start, end] with a type-specific structure


class DailyKind(StrEnum):
    SUM = "sum"  # cumulative, de-duplicated across sources (interval subtraction)
    SAMPLES = "samples"  # avg/min/max/count over health_sample rows
    INSTANT = "instant"  # avg/min/max/count/last over point values
    SLEEP = "sleep"  # asleep seconds per wake-up day, sessions de-duplicated
    SESSION = "session"  # count + duration, sessions de-duplicated


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- data models


def _scalar(
    name: str, lo: float, hi: float, **extra: tuple[type | object, object]
) -> type[BaseModel]:
    """``{"value": float}`` bounded to [lo, hi], plus optional extra fields."""
    fields: dict[str, tuple[type | object, object]] = {
        "value": (Annotated[float, Field(ge=lo, le=hi, allow_inf_nan=False)], ...),
        **extra,
    }
    return create_model(name, __base__=_Strict, **fields)  # type: ignore[call-overload, no-any-return]


class Sample(_Strict):
    time: AwareDatetime
    value: Finite


class SeriesData(_Strict):
    samples: Annotated[list[Sample], Field(max_length=20_000)]
    # SkinTemperature only: baseline the sample deltas refer to.
    baseline_celsius: Finite | None = None
    measurement_location: Shortstr | None = None


SleepStageName = Literal[
    "unknown", "awake", "sleeping", "out_of_bed", "light", "deep", "rem", "awake_in_bed"
]


class SleepStage(_Strict):
    stage: SleepStageName
    start_time: AwareDatetime
    end_time: AwareDatetime


class SleepData(_Strict):
    title: Title | None = None
    stages: Annotated[list[SleepStage], Field(max_length=1_000)] = []


class RoutePoint(_Strict):
    time: AwareDatetime
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    alt_m: Finite | None = None
    horizontal_accuracy_m: Finite | None = None


MAX_ROUTE_POINTS = 50_000
"""Most GPS points one ExerciseSession may carry (a limit shown in the dashboard)."""


class ExerciseData(_Strict):
    exercise_type: Shortstr  # e.g. "WALKING", "RUNNING" (HC constant name)
    exercise_type_id: int | None = None  # raw HC integer constant
    title: Title | None = None
    route: Annotated[list[RoutePoint], Field(max_length=MAX_ROUTE_POINTS)] | None = None


class MindfulnessData(_Strict):
    mindfulness_type: Shortstr | None = None
    title: Title | None = None


class NutritionData(_Strict):
    name: Title | None = None
    meal_type: Shortstr | None = None
    energy_kcal: Annotated[float, Field(ge=0, le=100_000, allow_inf_nan=False)] | None = None
    protein_g: Annotated[float, Field(ge=0, le=10_000, allow_inf_nan=False)] | None = None
    total_fat_g: Annotated[float, Field(ge=0, le=10_000, allow_inf_nan=False)] | None = None
    total_carbohydrate_g: Annotated[float, Field(ge=0, le=10_000, allow_inf_nan=False)] | None = (
        None
    )
    dietary_fiber_g: Annotated[float, Field(ge=0, le=10_000, allow_inf_nan=False)] | None = None
    sugar_g: Annotated[float, Field(ge=0, le=10_000, allow_inf_nan=False)] | None = None


class BloodPressureData(_Strict):
    systolic: Annotated[float, Field(ge=20, le=400, allow_inf_nan=False)]
    diastolic: Annotated[float, Field(ge=10, le=300, allow_inf_nan=False)]
    body_position: Shortstr | None = None
    measurement_location: Shortstr | None = None


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class TypeSpec:
    name: str
    shape: Shape
    daily: DailyKind
    unit: str | None  # unit of ``value`` / sample values (None: not a single scalar)
    model: type[BaseModel]
    value_keys: tuple[str, ...] = ("value",)  # keys of ``data`` feeding daily stats

    @property
    def end_required(self) -> bool:
        return self.shape is not Shape.INSTANT

    @property
    def uses_samples(self) -> bool:
        return self.shape is Shape.SERIES


SPECS: dict[str, TypeSpec] = {}


def _register(
    name: str,
    shape: Shape,
    daily: DailyKind,
    unit: str | None,
    model: type[BaseModel],
    value_keys: tuple[str, ...] = ("value",),
) -> None:
    SPECS[name] = TypeSpec(name, shape, daily, unit, model, value_keys)


def _cumulative(name: str, unit: str, hi: float) -> None:
    _register(name, Shape.INTERVAL, DailyKind.SUM, unit, _scalar(f"{name}Data", 0, hi))


def _instant(
    name: str, unit: str, lo: float, hi: float, **extra: tuple[type | object, object]
) -> None:
    _register(name, Shape.INSTANT, DailyKind.INSTANT, unit, _scalar(f"{name}Data", lo, hi, **extra))


def _series(name: str, unit: str) -> None:
    _register(name, Shape.SERIES, DailyKind.SAMPLES, unit, SeriesData)


_OPT_STR = (Shortstr | None, None)

# Tier 1
_cumulative("Steps", "count", 1_000_000)
_series("HeartRate", "bpm")
_instant("RestingHeartRate", "bpm", 10, 300)
_register("SleepSession", Shape.SESSION, DailyKind.SLEEP, None, SleepData, ())
_register("ExerciseSession", Shape.SESSION, DailyKind.SESSION, None, ExerciseData, ())
_cumulative("ActiveCaloriesBurned", "kcal", 100_000)
_cumulative("TotalCaloriesBurned", "kcal", 100_000)
_cumulative("Distance", "m", 10_000_000)
_instant("Weight", "kg", 1, 700)
_instant("OxygenSaturation", "percent", 0, 100)
_instant("HeartRateVariabilityRmssd", "ms", 0, 10_000)

# Tier 2
_series("Speed", "m/s")
_series("Power", "W")
_series("StepsCadence", "steps/min")
_series("CyclingPedalingCadence", "rpm")
_cumulative("FloorsClimbed", "floors", 10_000)
_cumulative("ElevationGained", "m", 100_000)
_instant("Vo2Max", "ml/min/kg", 0, 120, measurement_method=_OPT_STR)
_instant("RespiratoryRate", "breaths/min", 0, 200)
_instant("BasalMetabolicRate", "kcal/day", 0, 20_000)
_instant("Height", "m", 0.1, 3.0)
_instant("BodyFat", "percent", 0, 100)
_instant("LeanBodyMass", "kg", 0, 700)
_instant("BoneMass", "kg", 0, 100)
_instant("BodyWaterMass", "kg", 0, 700)
_register(
    "BloodPressure",
    Shape.INSTANT,
    DailyKind.INSTANT,
    "mmHg",
    BloodPressureData,
    ("systolic", "diastolic"),
)
_instant(
    "BloodGlucose",
    "mmol/L",
    0,
    100,
    specimen_source=_OPT_STR,
    meal_type=_OPT_STR,
    relationship_to_meal=_OPT_STR,
)
_instant("BodyTemperature", "celsius", 20, 50, measurement_location=_OPT_STR)
_series("SkinTemperature", "celsius_delta")
_cumulative("Hydration", "L", 1_000)
_register("Nutrition", Shape.INTERVAL, DailyKind.SUM, "kcal", NutritionData, ("energy_kcal",))
_register("MindfulnessSession", Shape.SESSION, DailyKind.SESSION, None, MindfulnessData, ())

# Sleep stages that do not count as "asleep" when summing sleep time.
NOT_ASLEEP_STAGES = frozenset({"awake", "out_of_bed", "awake_in_bed"})


def spec_for(type_name: str) -> TypeSpec | None:
    return SPECS.get(type_name)


def utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)
