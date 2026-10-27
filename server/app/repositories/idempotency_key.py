from sqlalchemy import select

from app.models.idempotency_key import IdempotencyKey
from app.repositories.base import Repository


class IdempotencyKeyRepository(Repository[IdempotencyKey]):
    model = IdempotencyKey

    def find(self, scope, key):
        return self.session.scalar(select(IdempotencyKey).where(
            IdempotencyKey.scope == scope, IdempotencyKey.idempotency_key == key,
        ))
