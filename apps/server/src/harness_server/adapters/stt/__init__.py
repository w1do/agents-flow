"""Адаптер распознавания речи: Protocol, OpenAI-совместимый клиент и фейк для тестов."""

from harness_server.adapters.stt.fake import FakeSpeechToText
from harness_server.adapters.stt.openai_compat import OpenAiCompatibleStt
from harness_server.adapters.stt.protocol import SpeechToText, SttError

__all__ = ["FakeSpeechToText", "OpenAiCompatibleStt", "SpeechToText", "SttError"]
