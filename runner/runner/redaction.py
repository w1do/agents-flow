"""Defense in depth for values, names, message history and binary artifacts."""

import decimal
import re

from .secrets import SECRET_NAME, current, normalize
from .safe_fs import sensitive
from .protected_text import redact_paths

TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")
ASSIGNMENT = re.compile(r"(?i)\b([A-Z0-9]*_(?:KEY|TOKEN|SECRET)|PASSWORD)\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s;]+)")
BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+")
MASK = "[REDACTED]"


def safe_path(path):
    return MASK if any(sensitive(part) for part in path.split("/")) else redact(path)


def safe_command(command):
    # Hide the whole command if any argument mentions protected filesystem data.
    return MASK if redact_paths(command) != command else redact(command)


def _text(raw, variants):
    raw = redact_paths(raw)
    raw = ASSIGNMENT.sub(r"\1=[REDACTED]", raw)
    raw = BEARER.sub(r"\1[REDACTED]", raw)
    for secret in variants:
        raw = raw.replace(secret, MASK)
    return TOKEN.sub(MASK, raw)


def redact(value):
    snapshot = current()
    variants = snapshot.variants
    numbers = set()
    for secret in snapshot.values:
        try:
            number = decimal.Decimal(normalize(secret))
            if number.is_finite():
                numbers.add(number)
        except decimal.InvalidOperation:
            pass

    def clean(item):
        if isinstance(item, str):
            return _text(item, variants)
        if isinstance(item, (list, tuple)):
            return [clean(part) for part in item]
        if isinstance(item, dict):
            result = {}
            for key, part in item.items():
                safe = _text(str(key), variants)
                base, suffix = safe, 0
                while safe in result:
                    suffix += 1
                    safe = f"{base}.{suffix}"
                result[safe] = MASK if SECRET_NAME.search(str(key)) else clean(part)
            return result
        if isinstance(item, (int, float, decimal.Decimal)) and not isinstance(item, bool):
            return MASK if decimal.Decimal(str(item)) in numbers else item
        return item

    return clean(value)


def redact_bytes(raw):
    """Use the same forms in UTF-8, UTF-16LE and UTF-16BE, even inside binary files."""
    encoded = [(v.encode(codec), MASK.encode(codec)) for v in current().variants
               for codec in ("utf-8", "utf-16-le", "utf-16-be")]
    for variant, mask in sorted(encoded, key=lambda pair: len(pair[0]), reverse=True):
        raw = raw.replace(variant, mask)
    # Generic credential patterns also cover credentials absent from the snapshot.
    return _text(raw.decode("utf-8", "surrogateescape"), ()).encode("utf-8", "surrogateescape")
