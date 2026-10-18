# Proposal: mvp-02-foundation

## Why

Остальные изменения MVP нужно где-то собирать, проверять и выкатывать. Каркас монорепо, конфигурация,
единая точка команд и CI появляются один раз и сразу в той форме, в которой проект будет жить
(ТЗ §3, §7, §15; preferences: два Compose-стека, GitLab CI до 10 минут).

## What Changes

- uv workspace: `apps/server` (пакет `harness_server`), `shared` (пакет `harness_shared`), Python 3.12.
- `harness_server.settings` (pydantic-settings, все ENV из ARCHITECTURE.md §9) и `harness_server.config`
  (загрузка `config/harness.yaml`, схема Pydantic). Сервер не стартует при невалидном ENV или конфиге.
- FastAPI-приложение `create_app()` с `GET /health` (живость) и `GET /health/ready` (БД доступна).
- CLI `harness-server` (typer): `serve`, `worker` (пустой цикл-заглушка), `migrate`, `check-config`.
- `./tools/harness`: `check`, `dev`, `migrate`, `fmt`.
- Docker-образ, `docker-compose.yml` (`migrate` → `server`, `worker`), `deploy/db/docker-compose.yml`,
  `.env.example`, `config/harness.example.yaml`.
- `.gitlab-ci.yml`: `check → build → deploy`.
- README для `apps/server`, `shared`, `db`.

## Capabilities

### New Capabilities

- `platform-config`: загрузка и проверка ENV и `harness.yaml`, проверки живости и готовности сервера.

### Modified Capabilities

Нет.

## Impact

- Новые каталоги: `apps/server`, `shared`, `db/migrations` (пустой env Alembic), `deploy/`, `config/`, `tools/`.
- Зависимости: fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, typer, httpx,
  pyyaml; dev: pytest, pytest-asyncio, ruff, mypy, respx, testcontainers.
- Зависит от: нет (может идти параллельно с `mvp-01`).

## Не входит

Таблицы и миграции домена (`mvp-03`), Telegram (`mvp-04`), консоль (после MVP).
