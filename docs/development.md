# Разработка

## Как идёт работа

1. Изменение описано в `openspec/changes/<id>/` (proposal, design при необходимости, specs, tasks).
2. Реализация идёт по `tasks.md` сверху вниз; каждая задача отмечается `- [x]` только после проверки из её описания.
3. Ревью сверяет diff со спецификацией (сценарии `#### Scenario` = приёмочные тесты).
4. После приёмки: `openspec archive <id>` переносит требования в `openspec/specs/`, PLAN.md обновляется.

Процесс ролей (Architect → Implementer → Reviewer, проверки, память) описан в глобальном CLAUDE.md
пользователя; проектные правила — в [CLAUDE.md](../CLAUDE.md).

## Локальный запуск (появится в mvp-02-foundation)

```bash
uv sync                               # зависимости workspace (apps/server, shared)
docker compose -f deploy/db/docker-compose.yml up -d   # Postgres
cp .env.example .env                  # заполнить значения (не коммитится)
cp config/harness.example.yaml config/harness.yaml
./tools/harness migrate
./tools/harness dev                   # server :8000 + worker
./tools/harness check                 # ruff, mypy, pytest
```

Webhook Telegram локально — через публичный туннель на `/telegram/webhook`; адрес в `HARNESS_PUBLIC_URL`.

## Тесты

| Уровень | Что | Как |
|---|---|---|
| domain | переходы статусов, redaction | чистые unit-тесты |
| services | бизнес-логика | фейковые адаптеры + реальный Postgres (testcontainers) |
| adapters | контракты Telegram, Polza, STT, GitLab, Novita | respx / записанные ответы |
| api / mcp | авторизация, валидация, коды ответов | httpx AsyncClient + MCP-клиент SDK |
| live | реальная песочница, бот, GitLab | `pytest -m live`, вручную, ключи из ENV |

## Стиль

- ruff (lint + format), mypy `--strict`, line-length 100.
- Async везде на I/O. Синхронные SDK вызываются через `asyncio.to_thread` внутри адаптера.
- Миграция Alembic на каждое изменение моделей; `alembic check` в CI.
- Сообщения коммитов: `<change-id>: <что сделано>`.
