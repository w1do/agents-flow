from datetime import datetime, timezone

LEASE_TTL_SECONDS = 60
POLL_INTERVAL_SECONDS = 5


def as_utc(value: datetime) -> datetime:
    # SQLite returns naive values even for DateTime(timezone=True).
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
