# Tasks

## 1. Типы и домен

- [ ] 1.1 В `shared` добавить `TaskKind`, `TaskStatus`, `TaskSource`, `TestsState` (`not_run`, `passed`, `failed`, `no_tests`), `TaskOut`, `TaskEventOut` — проверка: mypy, импорт из сервера
- [ ] 1.2 `domain/statuses.py` с таблицей переходов и `ensure_transition`; тесты: каждый допустимый переход, отказ на недопустимых, у каждого не конечного статуса есть выход — проверка: pytest
- [ ] 1.3 `domain/errors.py`: `DomainError`, `InvalidTransition`, `NotFound`, `Forbidden` — проверка: используются в тестах 1.2

## 2. Схема БД

- [ ] 2.1 ORM-модели всех таблиц из ARCHITECTURE.md §3 (UUIDv7, `created_at/updated_at`, индексы по `status`, `workspace_id`, `priority`) — проверка: mypy
- [ ] 2.2 Миграция `0001_initial` и проверка `alembic check` без расхождений — проверка: upgrade/downgrade на тестовой БД
- [ ] 2.3 Фикстура тестовой БД (testcontainers локально, сервис в CI) с откатом транзакции на тест — проверка: пустой тест с сессией проходит

## 3. Сервис задач

- [ ] 3.1 `services/tasks.py`: `create_task`, `change_status` (переход + событие в одной транзакции), `get_task`, `list_tasks` — проверка: тесты на сценарии «Допустимые переходы» и «Лента событий»
- [ ] 3.2 `claim_next_task(kinds, statuses)` с `FOR UPDATE SKIP LOCKED` — проверка: тест с двумя конкурентными сессиями (сценарий «Два воркера»)
- [ ] 3.3 `add_event(task_id, text, source)` для отчётов без смены статуса — проверка: pytest

## 4. HTTP

- [ ] 4.1 Зависимость авторизации `HARNESS_ADMIN_TOKEN` (`compare_digest`), `POST /tasks`, `GET /tasks/{id}` — проверка: тесты 201/200/401/404
- [ ] 4.2 Обновить ARCHITECTURE.md (§3 таблицы, §9 `HARNESS_ADMIN_TOKEN`), `.env.example`, README `db`, PLAN.md — проверка: ревью диффа документации

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового файла (модели, сервис, миграция), `memory_status` без устаревших файлов
