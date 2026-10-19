"""Токены задач для агентов: генерация и хеш для хранения (mvp-06, D-37).

Значение токена выдаётся один раз и в БД не хранится: только HMAC-SHA256 с HARNESS_SECRET_KEY.
Поэтому утечка таблицы task_tokens не даёт рабочих токенов без ключа сервера.

Префикс `aft_` нужен шаблону redaction (D-42): токен, попавший в вывод песочницы, закрывается им и
после рестарта worker, когда точного значения в памяти нет. Хеш считается от значения
целиком, с префиксом.
"""

import hashlib
import hmac
import secrets
from typing import Final

# Префикс формата токена задачи; шаблон redaction опирается на него (D-42).
TOKEN_PREFIX: Final = "aft_"
# 32 байта случайности: токен не угадывается перебором даже при известном формате.
_TOKEN_BYTES = 32


def generate() -> str:
    """Новый случайный токен задачи с префиксом TOKEN_PREFIX. Значение показывается один раз."""
    return TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str, key: str) -> str:
    """HMAC-SHA256 токена с ключом сервера; hex-строка из 64 символов.

    Одинаковый токен и ключ дают одинаковый хеш: по нему ищется запись в task_tokens. Значения
    token и key в текст исключений не выводятся.
    """
    digest = hmac.new(key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()
