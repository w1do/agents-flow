from app.models.idempotency_key import IdempotencyKey
from app.repositories.base import Repository


class IdempotencyKeyRepository(Repository[IdempotencyKey]):
    model = IdempotencyKey
