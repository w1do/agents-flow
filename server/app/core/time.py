from datetime import datetime, timezone

LEASE_TTL_SECONDS = 60
POLL_INTERVAL_SECONDS = 5


def as_utc(value: datetime) -> datetime:
    # SQLite возвращает время без часового пояса.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def now() -> datetime:
    return datetime.now(timezone.utc)
