from pathlib import Path
from typing import Protocol


class ConfigurationError(ValueError):
    """Safe configuration message suitable for the user."""


class TranscriptionError(RuntimeError):
    pass


class Transcriber(Protocol):
    async def transcribe(self, path: Path) -> str: ...
