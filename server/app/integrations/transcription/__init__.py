from app.integrations.transcription.base import ConfigurationError, Transcriber
from app.integrations.transcription.openai import OpenAITranscriber
from app.integrations.transcription.stub import StubTranscriber


def create_transcriber(settings) -> Transcriber:
    provider = settings.transcription_provider.strip().lower()
    if provider == "stub":
        return StubTranscriber()
    if provider == "openai":
        key = settings.transcription_api_key or settings.openai_api_key
        if key is None or not key.get_secret_value():
            raise ConfigurationError("Для транскрибации задайте TRANSCRIPTION_API_KEY или OPENAI_API_KEY.")
        return OpenAITranscriber(key.get_secret_value(),
                                 settings.openai_base_url or "https://api.openai.com/v1",
                                 settings.transcription_model)
    raise ConfigurationError("Неизвестный TRANSCRIPTION_PROVIDER. Доступны stub и openai.")
