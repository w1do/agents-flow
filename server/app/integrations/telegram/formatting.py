import re

from pydantic import SecretStr

from app.services.skill_content import redact

MESSAGE_LIMIT = 3500
BUTTONS = {
    "plan": (("Приступай", "approved"), ("Улучши план", "rejected"), ("Отклонить", "trash")),
    "result": (("Принять и опубликовать", "publish"), ("Доработать", "rework"),
               ("Оставить без публикации", "keep_ready")),
}
ACTION_CODES = {"approved": "a", "rejected": "n", "trash": "t", "publish": "p",
                "rework": "r", "keep_ready": "k"}


def safe_text(text, settings):
    text = str(text or "")
    secrets = [value.get_secret_value() for value in vars(settings).values()
               if isinstance(value, SecretStr) and value.get_secret_value()]
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, "[Секрет скрыт]")
    if re.search(r"\.env\b|^\s*(?:export\s+)?[A-Z][A-Z0-9_]+\s*=", text, re.M):
        return "Содержимое конфигурации скрыто. Полный текст — в панели."
    if "Traceback (most recent call last)" in text:
        return "Технические подробности — в панели."
    text = re.sub(r"(?i)\b(?:bearer\s+\S+|[\w-]*(?:token|secret|password|api_key)\s*[:=]\s*\S+)",
                  "[Секрет скрыт]", text)
    text = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b|\beyJ[A-Za-z0-9_.-]+", "[Секрет скрыт]", text)
    text = re.sub(r"(https?://)[^/\s]+@", r"\1[Секрет скрыт]@", text)
    return redact(text)


def units(text):
    return len(text.encode("utf-16-le")) // 2


def clip(text, limit):
    return text.encode("utf-16-le")[:max(0, limit) * 2].decode("utf-16-le", errors="ignore")


def message(heading, content, task_id, settings):
    text = safe_text(f"{heading}\n{content}".strip(), settings)
    link = safe_text(f"{settings.public_base_url.rstrip('/')}/tasks/{task_id}", settings)
    footer = f"\n\nПанель: {clip(link, 700)}"
    if units(text + footer) > MESSAGE_LIMIT:
        footer = "\n… Текст сокращён; полный текст — в панели." + footer
    return clip(text, MESSAGE_LIMIT - units(footer)) + footer


def keyboard(kind, task_id, revision=None):
    prefix = "p" if kind == "plan" else "r"
    revision = (revision or task_id).hex
    return {"inline_keyboard": [[{"text": label, "callback_data": f"{prefix}{ACTION_CODES[value]}{revision}"}]
                                for label, value in BUTTONS[kind]]}
