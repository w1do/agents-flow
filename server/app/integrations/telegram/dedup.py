"""Persist webhook outcomes in the existing idempotency table with their effects."""
from datetime import timedelta
from hashlib import sha256

from sqlalchemy import delete, select

from app.core import time
from app.models import IdempotencyKey

TTL = timedelta(hours=24)


def scope(settings):
    token = settings.telegram_bot_token.get_secret_value()
    return "telegram:" + sha256(token.split(":", 1)[0].encode()).hexdigest()


def result(session, namespace, update_id):
    row = session.scalar(select(IdempotencyKey).where(
        IdempotencyKey.scope == namespace, IdempotencyKey.idempotency_key == str(update_id)))
    if row and time.as_utc(row.created_at) + TTL > time.now():
        remaining = (time.as_utc(row.created_at) + TTL - time.now()).total_seconds()
        return row.response_body, remaining
    return None


def store(session, namespace, update_id, response):
    session.execute(delete(IdempotencyKey).where(
        IdempotencyKey.scope == namespace, IdempotencyKey.created_at <= time.now() - TTL))
    session.add(IdempotencyKey(scope=namespace, idempotency_key=str(update_id),
                              request_hash="telegram-update", response_code=200,
                              response_body=response, created_at=time.now()))


class Outcome:
    def __init__(self, session, runtime, update_id):
        self.session, self.runtime, self.update_id = session, runtime, update_id
        self.namespace, self.response, self.saved = scope(runtime.settings), {"ok": True}, False

    def commit(self):
        if not self.saved:
            store(self.session, self.namespace, self.update_id, self.response)
        self.session.commit()
        self.saved = True
        self.runtime.updates.complete(self.update_id)
