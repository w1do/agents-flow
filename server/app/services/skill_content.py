import logging
import re
import unicodedata
from hashlib import sha256

_PATTERNS = {
    "private_key": r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)",
    "github_token": r"(?<!\w)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})(?!\w)",
    "api_token": r"(?<!\w)(?:sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,})(?!\w)",
    "aws_key": r"(?<!\w)AKIA[A-Z0-9]{16}(?!\w)",
    "slack_token": r"(?<!\w)xox[baprs]-[A-Za-z0-9-]+(?!\w)",
    "agent_token": r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])",
}
_LETTERS = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ("a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "i", "k", "l", "m", "n", "o",
     "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"),
))


def inspect_content(content: str) -> list[str]:
    return [name for name, pattern in _PATTERNS.items() if re.search(pattern, content)]


def contains_secret(value: str) -> bool:
    return any(re.search(pattern, value) for pattern in _PATTERNS.values())


def redact(content: str) -> str:
    for pattern in _PATTERNS.values():
        content = re.sub(pattern, "[REDACTED]", content)
    return content


def sanitize(value):
    """Recursively redact text fields and keys without exposing their original values."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {redact(key) if isinstance(key, str) else key: sanitize(item)
                for key, item in value.items()}
    return value


def content_values(content: str) -> dict:
    return {"content": content, "content_hash": sha256(content.encode()).hexdigest()}


def warn(content: str) -> list[str]:
    matches = inspect_content(content)
    if matches:
        logging.getLogger(__name__).warning("Skill content matched secret patterns")
    return matches


def slug(value: str) -> str:
    translated = "".join(_LETTERS.get(char, char) for char in value.lower())
    ascii_text = unicodedata.normalize("NFKD", translated).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "skill"


def unique_filename(category: str, name: str, used: set[str]) -> str:
    base = f"{slug(category)}--{slug(name)}"
    filename, suffix = f"{base}.md", 2
    while filename in used:
        filename, suffix = f"{base}-{suffix}.md", suffix + 1
    used.add(filename)
    return filename
