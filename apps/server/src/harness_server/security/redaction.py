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
    # Префиксы git-провайдеров ловятся и после «_» (FOO_ghp_…), поэтому граница — это не буква
    # и не цифра (D-62).
    # GitLab: PAT, deploy, runner, OAuth и прочие токены с префиксом gl…- (D-60).
    (
        re.compile(
            r"(?<![A-Za-z0-9])gl(?:pat|dt|rt|cbt|oas|ptt|ft|imt|agent|soat)"
            r"-[A-Za-z0-9_.-]{20,}"
        ),
        REDACTED,
    ),
    # GitHub: classic PAT, OAuth, user-to-server, server-to-server, refresh (D-60).
    (re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}"), REDACTED),
    # GitHub fine-grained PAT (D-60).
    (re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,}"), REDACTED),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), REDACTED),  # Anthropic
    (re.compile(r"\baft_[A-Za-z0-9_-]{40,}"), REDACTED),  # токен задачи агента (D-42)
    # Схема авторизации остаётся, чтобы текст было понятно читать; сам токен заменяется.
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), rf"\1 {REDACTED}"),
    # Заголовок Basic git в любом регистре: значение с цифрой, «+» или «/» — base64,
    # а не слово (D-62).
    (
        re.compile(r"(?i)\b(basic)\s+(?=[A-Za-z0-9+/]*[0-9+/])[A-Za-z0-9+/]{16,}={0,2}"),
        rf"\1 {REDACTED}",
    ),
    # Пароль в адресе https://user:pass@host: пользователь остаётся, пароль заменяется (D-62).
    (re.compile(r"(?i)\b(https?://[^\s/@:]+):[^\s/@]+@"), rf"\1:{REDACTED}@"),
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
