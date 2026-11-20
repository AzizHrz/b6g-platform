from __future__ import annotations

from datetime import datetime, timezone


def now_iso(dt: datetime | None = None) -> str:
    """Horodatage ISO 8601 UTC avec millisecondes : 2026-11-20T10:15:00.123Z."""
    dt = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
