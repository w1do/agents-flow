from pathlib import Path


class StubTranscriber:
    def __init__(self, text="Тестовая голосовая задача"):
        self.text = text

    async def transcribe(self, path: Path) -> str:
        return self.text
