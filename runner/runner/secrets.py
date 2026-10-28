"""Immutable credential snapshots. Only configuration loading may extend them."""

import base64
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote, quote_plus

SECRET_NAME = re.compile(r"token|secret|password|(?:^|[_-])key$|api[_-]?key|authorization", re.I)


def normalize(value):
    value = value.strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


@lru_cache(maxsize=256)
def forms(secret):
    """One finite set of supported representations for every output boundary."""
    value = normalize(secret)
    bases = {secret, secret.strip()}
    if value:
        bases.update((value, f'"{value}"', f"'{value}'"))
    bases.discard("")
    result = set(bases)
    for text in bases:
        raw = text.encode("utf-8")
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            encoded = encode(raw).decode("ascii")
            result.update((encoded, encoded.rstrip("=")))
        for encode in (quote, quote_plus):
            encoded = encode(text, safe="")
            result.update((encoded, re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), encoded)))
        utf16 = text.encode("utf-16-be")
        escaped = "".join(f"\\u{int.from_bytes(utf16[i:i+2], 'big'):04x}"
                          for i in range(0, len(utf16), 2))
        result.update((raw.hex(), raw.hex().upper(), escaped,
                       re.sub(r"[a-f]", lambda m: m[0].upper(), escaped),
                       text.encode("unicode_escape").decode(), json.dumps(text)[1:-1]))
    return frozenset(result)


@dataclass(frozen=True, repr=False)
class SecretSnapshot:
    values: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def capture(cls, env, private=None):
        values = {v for k, v in env.items() if SECRET_NAME.search(k) and v}
        values.update(v for v in (private or {}).values() if v)
        return cls(frozenset(values))

    @property
    def variants(self):
        return sorted({v for secret in self.values for v in forms(secret)}, key=len, reverse=True)


_active = SecretSnapshot()


def install(snapshot):
    """Retain previous generations so already produced data stays protected."""
    global _active
    _active = SecretSnapshot(_active.values | snapshot.values)


def current():
    return _active
