from pathlib import Path
from tempfile import NamedTemporaryFile
from asyncio import timeout

from app.integrations import transcription
from app.integrations.telegram.client import MAX_AUDIO_BYTES, TelegramError

AUDIO_TIMEOUT = 120

async def transcribe(runtime, media, *, voice=False, chat="unknown"):
    if media.file_size > MAX_AUDIO_BYTES:
        raise TelegramError("Аудио больше 20 МБ. Отправьте файл поменьше или напишите текстом.")
    provider = transcription.create_transcriber(runtime.settings)
    if runtime.audio_active >= 2 or chat in runtime.audio_chats:
        raise TelegramError("Сейчас обрабатываются другие аудио. Повторите запрос позже.")
    runtime.audio_active += 1
    runtime.audio_chats.add(chat)
    suffix = ".ogg" if voice else Path(media.file_name).suffix.lower()
    if suffix not in {".ogg", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".flac"}:
        suffix = ".mp3"
    path = None
    try:
        with NamedTemporaryFile(prefix="telegram-", suffix=suffix, delete=False) as temporary:
            path = Path(temporary.name)
        try:
            async with timeout(AUDIO_TIMEOUT):
                await runtime.bot.download(media.file_id, path)
                return await provider.transcribe(path)
        except TimeoutError:
            raise TelegramError("Обработка аудио заняла слишком много времени. Повторите позже.") from None
    finally:
        if path:
            path.unlink(missing_ok=True)
        runtime.audio_active -= 1
        runtime.audio_chats.discard(chat)
