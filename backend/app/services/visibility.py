"""The one SQL predicate that hides manually excluded measures from every analysis query.

An exclusion lives in ``record_exclusion`` (keyed by type + Health Connect id), never on the
``health_record`` row, so no ingest path can reset it (ADR 0011). Anything that reads
``health_record`` to compute what the dashboard shows adds ``not_excluded()`` next to
``deleted_at IS NULL``. Inventory and storage deliberately do not: they describe what is stored.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, exists

from app.models import HealthRecord, RecordExclusion


def not_excluded() -> ColumnElement[bool]:
    return ~exists().where(
        RecordExclusion.type == HealthRecord.type, RecordExclusion.hc_id == HealthRecord.hc_id
    ).correlate(HealthRecord)
