"""Генератор UUIDv7 без зависимостей (D-21): Python 3.12 не имеет uuid.uuid7, а Postgres 16 не имеет
uuidv7()."""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_last_seq = 0
# Поле counter — 12 бит (rand_a в RFC 9562); при переполнении метка времени сдвигается вперёд.
_SEQ_MAX = 0xFFF


def uuid7() -> uuid.UUID:
    """UUIDv7 (RFC 9562): 48 бит unix-мс, версия 7, 12 бит счётчика, вариант 10, 62 бита случайных.

    Внутри процесса значения строго возрастают: в той же миллисекунде (или при откате часов) счётчик
    увеличивается, при переполнении счётчика метка времени сдвигается на 1 мс вперёд.
    """
    global _last_ms, _last_seq
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms > _last_ms:
            _last_ms = now_ms
            # Старший бит счётчика оставляем нулём, чтобы в этой мс было место для увеличений.
            _last_seq = int.from_bytes(os.urandom(2)) & 0x7FF
        else:
            _last_seq += 1
            if _last_seq > _SEQ_MAX:
                _last_ms += 1
                _last_seq = 0
        ms, seq = _last_ms, _last_seq
    rand_b = int.from_bytes(os.urandom(8)) & ((1 << 62) - 1)
    return uuid.UUID(int=(ms << 80) | (0x7 << 76) | (seq << 64) | (0b10 << 62) | rand_b)
