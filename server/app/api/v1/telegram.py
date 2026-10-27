import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.api.deps import Database
from app.integrations.telegram import dedup
from app.integrations.telegram.updates import handle
from app.schemas.telegram import Update

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1024 * 1024


@router.post("/webhook")
async def webhook(request: Request, session: Database):
    runtime = request.app.state.telegram
    secret = runtime.settings.telegram_webhook_secret
    expected = secret.get_secret_value() if secret else ""
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(401, "Неверный секрет Telegram webhook")
    content_length = request.headers.get("content-length")
    if content_length:
        length, maximum = content_length.lstrip("0") or "0", str(MAX_WEBHOOK_BYTES)
        if len(length) > len(maximum) or (length.isdecimal() and length > maximum
                                        and len(length) == len(maximum)):
            raise HTTPException(413, "Тело webhook превышает допустимый размер")
    try:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_WEBHOOK_BYTES:
                raise HTTPException(413, "Тело webhook превышает допустимый размер")
            body.extend(chunk)
        update = Update.model_validate(json.loads(body))
    except HTTPException:
        raise
    except (ValueError, ValidationError, UnicodeDecodeError):
        raise HTTPException(422, "Некорректный Telegram update") from None
    reservation = runtime.updates.acquire(update.update_id)
    if reservation == "done":
        return {"ok": True}
    if reservation in {"busy", "full"}:
        raise HTTPException(503, "Приём update занят; повторите позже")
    outcome = dedup.Outcome(session, runtime, update.update_id)
    try:
        existing = dedup.result(session, outcome.namespace, update.update_id)
        session.rollback()
        if existing is not None:
            response, remaining = existing
            runtime.updates.complete(update.update_id, ttl=remaining)
            return response
        await handle(session, runtime, update, outcome)
        if not outcome.saved:
            outcome.commit()
        return outcome.response
    except asyncio.CancelledError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.warning("telegram_update_failed")
        raise HTTPException(503, "Не удалось обработать update; повторите позже") from None
    finally:
        runtime.updates.release(update.update_id)
