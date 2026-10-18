"""Фейк распознавания речи для тестов: отдаёт заданный текст или заданную ошибку."""

from harness_server.adapters.stt.protocol import SttError


class FakeSpeechToText:
    """Фейк SpeechToText: запоминает вызовы, возвращает text или бросает error."""

    def __init__(self, text: str = "распознанный текст", *, error: SttError | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[int, str, str]] = []  # (len(audio), filename, mime_type)

    async def transcribe(self, audio: bytes, *, filename: str, mime_type: str) -> str:
        self.calls.append((len(audio), filename, mime_type))
        if self.error is not None:
            raise self.error
        stripped = self.text.strip()
        if not stripped:
            raise SttError("stt empty transcription")
        return stripped
