# Tasks

## 1. Каркас workspace

- [ ] 1.1 Создать корневой `pyproject.toml` (uv workspace), `apps/server/pyproject.toml` (пакет `harness_server`, entrypoint `harness-server`), `shared/pyproject.toml` (пакет `harness_shared`) — проверка: `uv sync` проходит, `uv run harness-server --help` печатает справку
- [ ] 1.2 Настроить ruff (line-length 100), mypy strict, pytest-asyncio в корневом `pyproject.toml` — проверка: `uv run ruff check . && uv run mypy apps shared` без ошибок
- [ ] 1.3 Создать `tools/harness` с командами `check`, `fmt`, `dev`, `migrate` — проверка: `./tools/harness check` запускается и проходит на пустом проекте

## 2. Конфигурация

- [ ] 2.1 Реализовать `settings.py` (все ENV из ARCHITECTURE.md §9, `SecretStr` для секретов) с тестами на отсутствие обязательных переменных — проверка: pytest
- [ ] 2.2 Реализовать `config.py` (`HarnessConfig`, `WorkspaceConfig`, `SandboxConfig`, `GitLabConfig`), запрет полей-секретов, уникальность `id`; тесты на сценарии спецификации — проверка: pytest
- [ ] 2.3 Добавить `config/harness.example.yaml` и `.env.example` (без значений секретов) — проверка: `harness-server check-config` с примером проходит в тесте
- [ ] 2.4 Команда `harness-server check-config` — проверка: тест CLI через `CliRunner`

## 3. Приложение

- [ ] 3.1 `create_app()` с lifespan (engine БД), `GET /health`, `GET /health/ready`; тесты на 200/503 — проверка: pytest
- [ ] 3.2 Команды `serve` (uvicorn) и `worker` (цикл с интервалом из настроек, пока без задач, корректная остановка по SIGTERM) — проверка: тест остановки worker
- [ ] 3.3 Пустой Alembic env в `db/migrations` на async engine и команда `migrate` — проверка: `alembic upgrade head` на пустой БД проходит

## 4. Деплой и CI

- [ ] 4.1 `Dockerfile` (multi-stage, uv, non-root) — проверка: `docker build` и `docker run … harness-server --help`
- [ ] 4.2 `docker-compose.yml` (`migrate` → `server`, `worker`; `dokploy-network` external; только `expose`) и `deploy/db/docker-compose.yml` — проверка: `docker compose config` валиден
- [ ] 4.3 `.gitlab-ci.yml`: check (ruff, mypy, pytest c Postgres service, `openspec validate --all`), build (registry cache, теги `:$CI_COMMIT_SHORT_SHA`, `:main`), deploy (curl webhook) — проверка: пайплайн зелёный на MR
- [ ] 4.4 README в `apps/server`, `shared`, `db`; ARCHITECTURE.md §9–10 сверить с фактическими ENV и сервисами; PLAN.md статус — проверка: команды из README выполняются как написано

## 5. Память проекта

- [ ] 5.1 `memory_update` по всем новым путям (или `memory sync`), `memory_annotate` для каждого нового файла, `memory_project_structure` обновлён, `memory_status` без устаревших файлов
