import logging
import re
import unicodedata
from hashlib import sha256

_PATTERNS = {
    "private_key": r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)",
    "github_token": r"(?<!\w)ghp_[A-Za-z0-9]{20,}(?!\w)",
    "api_token": r"(?<!\w)sk-[A-Za-z0-9]{20,}(?!\w)",
    "aws_key": r"(?<!\w)AKIA[A-Z0-9]{16}(?!\w)",
}
_LETTERS = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ("a", "b", "v", "g", "d", "e", "yo", "zh", "z", "i", "i", "k", "l", "m", "n", "o",
     "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"),
))


def inspect_content(content: str) -> list[str]:
    return [name for name, pattern in _PATTERNS.items() if re.search(pattern, content)]


def redact(content: str) -> str:
    for pattern in _PATTERNS.values():
        content = re.sub(pattern, "[REDACTED]", content)
    return content


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
