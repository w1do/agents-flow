"""UUIDv7 из db/ids.py: версия, вариант, монотонность и метка времени (D-21)."""

import time
import uuid
from itertools import pairwise

from harness_server.db.ids import uuid7


def test_uuid7_version_and_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_strictly_increasing() -> None:
    values = [uuid7() for _ in range(10_000)]

    assert all(later > earlier for earlier, later in pairwise(values))


def test_uuid7_timestamp_is_current() -> None:
    before_ms = time.time_ns() // 1_000_000
    value = uuid7()
    after_ms = time.time_ns() // 1_000_000

    assert before_ms <= value.int >> 80 <= after_ms + 5
