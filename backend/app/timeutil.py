"""Local-day computation. The offset carried by the record wins over the server timezone."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def local_date(ts: datetime, offset_s: int | None, fallback_tz: ZoneInfo) -> date:
    """Calendar day of ``ts`` as lived by the user.

    ``offset_s`` is Health Connect's zoneOffset (seconds east of UTC). When the record
    has no offset we fall back to the configured zone (Europe/Rome), DST-aware.
    """
    ts = ts.astimezone(UTC)
    if offset_s is not None:
        return (ts + timedelta(seconds=offset_s)).date()
    return ts.astimezone(fallback_tz).date()
