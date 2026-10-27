import asyncio
import logging

from app.integrations.telegram import client
from app.integrations.telegram.formatting import safe_text
from app.integrations.telegram.state import ActionCache, FeedbackCache, UpdateCache

logger = logging.getLogger(__name__)
DELIVERY_TIMEOUT = 30


class Runtime:
    def __init__(self, settings):
        self.settings, self.bot = settings, client.create_client(settings)
        self.updates, self.actions = UpdateCache(), ActionCache()
        self.feedback = FeedbackCache(actions=self.actions)
        self.audio_active, self.audio_chats = 0, set()

    async def send(self, chat, text, markup=None):
        try:
            async with asyncio.timeout(DELIVERY_TIMEOUT):
                return await self.bot.send_message(chat, safe_text(text, self.settings), markup)
        except client.TelegramError as error:
            logger.warning("telegram_send_failed")
            return error
        except Exception:
            logger.warning("telegram_send_failed")
            return None

    async def answer(self, callback_id, text):
        try:
            async with asyncio.timeout(DELIVERY_TIMEOUT):
                await self.bot.answer_callback(callback_id, text)
        except Exception:
            logger.warning("telegram_callback_answer_failed")
