"""Удаление секретов из текста, который уходит наружу: в Telegram, логи и БД.

Два источника замен: точные значения секретов из настроек, которые передаёт вызывающий, и шаблоны
известных форматов токенов. Шаблоны нужны на случай, когда секрет попал в текст не из ENV, например
из ответа внешнего API или из текста задачи.
"""

import re
from collections.abc import Iterable
from typing import Final

REDACTED: Final = "[REDACTED]"
# Короткое значение (например, «1») заменило бы обычные слова в тексте, поэтому его не заменяем.
_MIN_EXTRA_VALUE_LENGTH: Final = 8
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Граница только по цифрам: токен в URL идёт как «/bot123456:…», перед цифрами стоит буква.
    (re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"), REDACTED),  # токен Telegram-бота
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"), REDACTED),  # GitLab PAT
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), REDACTED),  # Anthropic
    (re.compile(r"\baft_[A-Za-z0-9_-]{40,}"), REDACTED),  # токен задачи агента (D-42)
    # Схема авторизации остаётся, чтобы текст было понятно читать; сам токен заменяется.
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), rf"\1 {REDACTED}"),
)


def redact(text: str, extra_values: Iterable[str] = ()) -> str:
    """Заменяет точные значения extra_values (длиной ≥ 8, сначала самые длинные) и шаблоны токенов.

    Длинные значения идут первыми: короткое значение, входящее в длинное, не должно оставить
    от длинного половину секрета.
    """
    values = sorted(
        {value for value in extra_values if len(value) >= _MIN_EXTRA_VALUE_LENGTH},
        key=len,
        reverse=True,
    )
    for value in values:
        text = text.replace(value, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
