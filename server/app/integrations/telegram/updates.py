import logging

from app.integrations.telegram import audio, buttons
from app.integrations.transcription.base import ConfigurationError
from app.repositories.project import ProjectRepository
from app.schemas.tasks import TaskCreate
from app.services import tasks

logger = logging.getLogger(__name__)


async def handle(session, runtime, update, outcome):
    query = update.callback_query
    message = query.message if query else update.message
    if message is None:
        return
    projects = ProjectRepository(session).list(telegram_chat_id=str(message.chat.id), limit=2)
    if len(projects) != 1:
        logger.info("telegram_chat_unbound_or_ambiguous")
        return
    project = projects[0]
    session.rollback()
    if query:
        await buttons.callback(session, runtime, project, query, outcome)
        return
    if await buttons.feedback(session, runtime, project, message, outcome):
        return
    media = message.voice or message.audio
    if media:
        try:
            text = await audio.transcribe(runtime, media, voice=message.voice is not None,
                                          chat=str(message.chat.id))
        except ConfigurationError:
            await runtime.send(str(message.chat.id),
                               "Обработка аудио не настроена. Отправьте задачу текстом.")
            return
        except Exception:
            logger.warning("telegram_audio_failed")
            await runtime.send(str(message.chat.id),
                               "Не удалось обработать аудио до 20 МБ. Повторите или напишите текстом.")
            return
        source = "telegram_voice"
    else:
        text, source = message.text, "telegram_text"
    if not isinstance(text, str) or not text.strip():
        return
    tasks.create(session, project.id, TaskCreate(title=text.strip()[:120], description=text,
                                               source_type=source, source_text=text))
    outcome.commit()
