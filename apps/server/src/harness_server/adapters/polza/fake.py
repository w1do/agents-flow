"""Фейк маршрутизатора для тестов: заданный ответ или заданная ошибка, без сети."""

from harness_server.adapters.polza.protocol import RouterError, RouterReply


class FakeRouter:
    """Фейк Router: возвращает заданный content или бросает error; пишет вызовы в calls."""

    def __init__(self, content: str | None = None, *, error: RouterError | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[tuple[str, str]] = []  # (system_prompt, user_text)

    async def complete(self, *, system_prompt: str, user_text: str) -> RouterReply:
        self.calls.append((system_prompt, user_text))
        if self.error is not None:
            raise self.error
        if self.content is None:
            raise RouterError("invalid_response")
        return RouterReply(content=self.content, model="fake/router")
