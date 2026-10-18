# Tasks

Порядок обязателен. Точные сигнатуры, схема и имена тестов — в design.md (разделы указаны в скобках).
После каждой группы: `uv run ruff format . && ./tools/harness check`. Новых зависимостей не добавлять.
Если шаг невозможно выполнить по тексту design.md — остановиться и сообщить, не придумывать замену.

## 1. Типы и домен

- [x] 1.1 `shared/src/harness_shared/tasks.py` и `sandboxes.py`: enums и DTO (design §1) — проверка: `uv run mypy apps shared`, импорт `from harness_shared.tasks import TaskStatus` в сервере
- [x] 1.2 `apps/server/src/harness_server/domain/__init__.py`, `domain/errors.py` (design §2) — проверка: `test_domain_error_codes`
- [x] 1.3 `domain/statuses.py` (design §3) и `tests/test_statuses.py` (все тесты из design «Test strategy») — проверка: `uv run pytest apps/server/tests/test_statuses.py`

## 2. Схема БД

- [x] 2.1 `db/__init__.py`, `db/ids.py` (design §4) и `tests/test_ids.py` — проверка: `uv run pytest apps/server/tests/test_ids.py`
- [x] 2.2 `db/base.py`, `db/session.py` (design §5, §9) — проверка: mypy
- [x] 2.3 `db/models/{__init__,tasks,planning,sandboxes,telegram}.py` по таблице design §6 (явные имена индексов/UNIQUE/CHECK, `use_alter=True` на `tasks.spec_item_id`, без `relationship()`) — проверка: mypy
- [x] 2.4 `db/migrations/env.py` (design §8): `disable_existing_loggers=False`, `target_metadata = Base.metadata` — проверка: тест 2.6
- [x] 2.5 Ручная миграция `db/migrations/versions/20261018_0001_initial.py` (design §7) — проверка: тест 2.6
- [x] 2.6 Фикстуры `migrated_database_url`, `db_engine`, `db_session`, `committed_session_factory`, константа `TRUNCATE_ALL` в `tests/conftest.py`; `tests/test_migrations.py` (3 теста) — проверка: `uv run pytest apps/server/tests/test_migrations.py`; при `modify_type` в `alembic check` — стоп и отчёт (design §7)

## 3. Сервис задач

- [x] 3.1 `services/__init__.py`, `services/tasks.py`: `create_task`, `get_task`, `list_tasks`, `list_task_events`, `change_status`, `add_event` (design §10) и `tests/test_task_service.py` — проверка: сценарии «Неизвестный статус», «Пропуск этапа», «Допустимый переход», «История задачи»
- [x] 3.2 `claim_next_task` (design §10) и `tests/test_task_queue.py` — проверка: сценарии «Два воркера», «Приоритет и порядок», «Занятая задача пропускается»

## 4. HTTP и настройки

- [x] 4.1 `settings.py`: `_ADMIN_TOKEN_MIN_LENGTH = 32`, валидатор `_check_admin_token_length` (design §13); тесты в `test_settings.py` — проверка: `uv run pytest apps/server/tests/test_settings.py`
- [x] 4.2 `api/deps.py` (design §11), `api/tasks.py` (design §12), `app.py`: `create_engine`/`create_session_factory`, `app.state.session_factory`, `include_router` — проверка: `tests/test_tasks_api.py` (все тесты из design), сценарии «Без токена», «Неверный токен», «Создание задачи»

## 5. Хвосты ревью mvp-02

- [x] 5.1 `db/migrations/env.py`: `fileConfig(..., disable_existing_loggers=False)` (сделано в 2.4) — проверка: `test_migrate_keeps_application_loggers_enabled`
- [x] 5.2 `config.py::_SECRET_SEGMENTS`: добавить `tokens, secrets, passwd, pwd, credential, credentials`; `GitLabConfig.base_url` без userinfo (design §14); тесты в `test_config.py` — проверка: `uv run pytest apps/server/tests/test_config.py`

## 6. Документация

- [x] 6.1 ARCHITECTURE.md: §2 — пакеты `domain/`, `db/`, `services/`, `api/tasks.py`, `api/deps.py` (уточнить строки дерева); §3 — колонки по design §6 (добавить `api` в `source` задач, `source` событий `telegram/agent/worker/api`, PK и `processed_at` у `telegram_updates`, `uq_spec_items_workspace_change_key`); §9 — `HARNESS_ADMIN_TOKEN` «≥ 32 символов, с mvp-03; не задан → `/tasks` отвечает 401», список сегментов секретов, запрет userinfo в `gitlab.base_url` — проверка: ревью диффа
- [x] 6.2 `.env.example`: строка `HARNESS_ADMIN_TOKEN=` с комментарием «mvp-03: операторский bearer для /tasks, ≥ 32 символов (openssl rand -hex 32)»; правка только этой строки и комментария, по разрешению оркестратора — проверка: ревью диффа — N/A: правка `.env*` запрещена оркестратором; `HARNESS_ADMIN_TOKEN` уже есть в `.env.example` (ревью mvp-02), требование ≥ 32 символов описано в ARCHITECTURE.md §9.
- [x] 6.3 `db/README.md` (ревизия `0001`, список таблиц, `alembic check`, фикстуры тестов БД), `apps/server/README.md` (эндпоинты `POST /tasks`, `GET /tasks/{id}`, заголовок `Authorization: Bearer`), `shared/README.md` (`harness_shared/tasks.py`, `sandboxes.py`), `docs/glossary.md` (строки `TaskEventSource`, `AgentRole`) — проверка: ревью диффа
- [x] 6.4 PLAN.md: статус `mvp-03-task-store` → `review`, «Следующий шаг» без изменений — проверка: ревью диффа
- [x] 6.5 `openspec validate mvp-03-task-store --strict` и `openspec validate --all` — проверка: без ошибок

## 7. Память проекта

- [x] 7.1 `memory_update` по всем изменённым и новым путям, `memory_annotate` для каждого нового и изменённого файла (модели, сервис, миграция, API, тесты, документация), `memory_status` без устаревших файлов; вернуть список путей оркестратору
