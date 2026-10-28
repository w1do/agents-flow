"""Byte limits apply before claim normalization or removal of unknown fields."""
import json

MAX_RESULT_BYTES = 256 * 1024
MAX_DEPTH = 32


def bounded_payload(data):
    pending = [(data, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise ValueError("Report payload exceeds nesting limit")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend((item, depth + 1) for item in value)
    if len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Report payload exceeds 256 KiB")
    return data
