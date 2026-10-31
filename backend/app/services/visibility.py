"""The one SQL predicate that hides manually excluded measures from every analysis query.

An exclusion lives in ``record_exclusion`` (keyed by type + Health Connect id), never on the
``health_record`` row, so no ingest path can reset it (ADR 0011). Anything that reads
``health_record`` to compute what the dashboard shows adds ``not_excluded()`` next to
``deleted_at IS NULL``. Inventory and storage deliberately do not: they describe what is stored.

The official Health Connect daily aggregates (``daily_metric.source = 'hc_official'``) are computed
by Health Connect and *include* the excluded measure. For a (type, day) with an excluded record
the official row is therefore ignored and the computed one (which skips the record) is used:
``daily_visible()``, added to every dashboard read of ``daily_metric`` (ADR 0011, 0.9.1). It is
evaluated at read time, so it also covers aggregates the Reader re-sends later, restoring brings the
official row back, and nothing has to be recomputed.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, exists, select

from app.models import DailyMetric, HealthRecord, RecordExclusion


def not_excluded() -> ColumnElement[bool]:
    return ~exists().where(
        RecordExclusion.type == HealthRecord.type, RecordExclusion.hc_id == HealthRecord.hc_id
    ).correlate(HealthRecord)


def _day_has_exclusion() -> ColumnElement[bool]:
    """True when the (type, local_date) of the ``daily_metric`` row holds a live excluded record."""
    return exists(
        select(1)
        .select_from(
            RecordExclusion.__table__.join(
                HealthRecord.__table__,
                and_(
                    HealthRecord.type == RecordExclusion.type,
                    HealthRecord.hc_id == RecordExclusion.hc_id,
                ),
            )
        )
        .where(
            HealthRecord.type == DailyMetric.type,
            HealthRecord.local_date == DailyMetric.local_date,
            HealthRecord.deleted_at.is_(None),
        )
    ).correlate(DailyMetric)


def official_ignored() -> ColumnElement[bool]:
    """The row is an official aggregate that an exclusion on its day makes unusable."""
    return and_(DailyMetric.source == "hc_official", _day_has_exclusion())


def daily_visible() -> ColumnElement[bool]:
    """Add to every ``select(DailyMetric)`` that feeds a chart, KPI, report or CSV."""
    return ~official_ignored()
