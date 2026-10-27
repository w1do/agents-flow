import json
from hashlib import sha256

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError

from app.repositories.idempotency_key import IdempotencyKeyRepository


def _response(record):
    if record.response_code == 204:
        return Response(status_code=204)
    return JSONResponse(status_code=record.response_code, content=record.response_body)


def execute(session, scope, key, body, operation, status=200, empty_status=None):
    request_hash = sha256(json.dumps(jsonable_encoder(body), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
    repo = IdempotencyKeyRepository(session)
    existing = repo.find(scope, key)
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key conflict")
        return _response(existing)
    try:
        record = repo.create(scope=scope, idempotency_key=key, request_hash=request_hash,
                             response_code=0, response_body={})
    except IntegrityError:
        session.rollback()
        existing = repo.find(scope, key)
        if existing is None or existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key conflict") from None
        return _response(existing)
    try:
        result = operation()
        record.response_code = empty_status if result is None and empty_status else status
        record.response_body = jsonable_encoder(result)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _response(record)
