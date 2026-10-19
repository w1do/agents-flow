# Разработка

## Как идёт работа

1. Изменение описано в `openspec/changes/<id>/` (proposal, design при необходимости, specs, tasks).
2. Реализация идёт по `tasks.md` сверху вниз; каждая задача отмечается `- [x]` только после проверки из её описания.
3. Ревью сверяет diff со спецификацией (сценарии `#### Scenario` = приёмочные тесты).
4. После приёмки: `openspec archive <id>` переносит требования в `openspec/specs/`, PLAN.md обновляется.

Процесс ролей (Architect → Implementer → Reviewer, проверки, память) описан в глобальном CLAUDE.md
пользователя; проектные правила — в [CLAUDE.md](../CLAUDE.md).

## Локальный запуск

```bash
uv sync                               # зависимости workspace (apps/server, shared)
cp .env.example .env                  # заполнить секреты (не коммитится); пароль БД уже совпадает с командой ниже
cp config/harness.example.yaml config/harness.yaml
docker run -d --name harness-pg -p 127.0.0.1:5432:5432 -e POSTGRES_DB=harness -e POSTGRES_USER=harness -e POSTGRES_PASSWORD=CHANGE_ME postgres:16-alpine
./tools/harness migrate               # миграции до head
./tools/harness dev                   # server на 127.0.0.1:8000 и worker (остановка по Ctrl+C)
curl -fsS localhost:8000/health/ready # в другом терминале: 200 при доступной БД
./tools/harness check                 # ruff, ruff format, mypy, pytest (Postgres для тестов поднимается сам, нужен Docker)
```

Локальная БД слушает только `127.0.0.1:5432`. Удалить: `docker rm -f harness-pg`. Если контейнер
уже существует, сначала удалите его. Пароль `CHANGE_ME` задан в `.env.example` и совпадает с
`POSTGRES_PASSWORD`; для локальной БД его можно оставить. Стек `deploy/db` предназначен для Dokploy
и описан в [db/README.md](../db/README.md).

Команды CLI, сборка образа и проверка compose — в `apps/server/README.md`, `db/README.md` и
[deployment.md](deployment.md).

Webhook Telegram локально — через публичный туннель на `/telegram/webhook`; адрес в `HARNESS_PUBLIC_URL`.
Пошаговая работа без веб-панели (Telegram и CLI, проверка, частые проблемы): [operating-without-ui.md](operating-without-ui.md).

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
- Миграция Alembic на каждое изменение моделей; `alembic check` в CI (включается в mvp-03, когда появится target_metadata).
- Сообщения коммитов: `<change-id>: <что сделано>`.
