from datetime import datetime, timezone

from app.core.config import get_settings


def lease_ttl_seconds() -> int:
    return get_settings().lease_ttl_seconds


def poll_interval_seconds() -> int:
    return get_settings().poll_interval_seconds


def as_utc(value: datetime) -> datetime:
    # SQLite возвращает время без часового пояса.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def now() -> datetime:
    return datetime.now(timezone.utc)
