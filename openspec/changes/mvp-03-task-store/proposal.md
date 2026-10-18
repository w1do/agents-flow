# Proposal: mvp-03-task-store

## Открытые вопросы

Нет. Все решения приняты и записаны в docs/decisions.md (D-21 … D-26). Разрешение на правку `.env.example`
(шаблон без секретов) оркестратор выдаёт Implementer явно: файл подпадает под маску `.env*`.

## Why

Postgres — единственный источник правды (ТЗ §2 п.7). Telegram, MCP и worker должны работать с одной моделью
задачи и одними правилами смены статуса, иначе канбан и сообщения разойдутся. Это изменение даёт схему,
машину статусов и сервис задач, на которые опираются все следующие изменения (ТЗ §4, §7, §16.0 п.2, §16.1 A5).

## Goals

- Одна функция смены статуса (`services.tasks.change_status`) для всех входов; переходы только через
  `domain/statuses.py`.
- Каждая смена статуса и каждый отчёт пишут `task_events` в той же транзакции.
- Очередь без гонок: `SELECT … FOR UPDATE SKIP LOCKED` + переход + событие одним коммитом.
- Схема всех 9 таблиц MVP одной миграцией `0001`; `alembic check` без расхождений.
- `POST /tasks`, `GET /tasks/{id}` под временным `HARNESS_ADMIN_TOKEN` (fail-closed).
- Хвосты ревью mvp-02: логгеры при миграции, расширенный фильтр секретов в `harness.yaml`, запрет userinfo
  в `gitlab.base_url`, минимальная длина `HARNESS_ADMIN_TOKEN`.

## Non-Goals (не входит)

- Подключение очереди к циклу worker (`worker.py` не меняется) — `mvp-06-sandbox-runtime`.
- Короткие 8-символьные id в Telegram, `notify` — `mvp-04-telegram-intake`.
- Задачи kind `check` (переходы и создание) — `check-tasks`; в mvp-03 `create_task(kind=check)` → `unsupported_kind`.
- Статусы `stalled`, `paused` в таблице переходов — `agent-heartbeat`, `task-pause-resume` (значения есть в
  enum и CHECK, но переходов в них нет).
- Таблицы `workspaces`, `agents`, `processes`, `sessions`, `operator_tokens`, `audit_log` — после MVP.
- Операторские токены со скоупами — `operator-tokens`. Канбан-экран, архивация.
- ORM-relationships между моделями (запросы явные, без ленивой загрузки в async).

## What Changes

- `shared` (`harness_shared.tasks`, `harness_shared.sandboxes`): `TaskKind`, `TaskStatus` (12 статусов ТЗ v5),
  `TaskSource` (`telegram`, `spec`, `mcp`, `api`), `TaskEventSource` (`telegram`, `agent`, `worker`, `api`),
  `TestsState`, `SandboxStatus`, `AgentRole`; DTO `TaskCreateIn`, `TaskOut`, `TaskEventOut`, `TaskDetailOut`.
- `domain/statuses.py` (таблица переходов, начальные и конечные статусы), `domain/errors.py`.
- `db/`: `Base` с naming convention, генератор UUIDv7, фабрика сессий, ORM-модели 9 таблиц
  (ARCHITECTURE.md §3), миграция `0001_initial`, `env.py` с `target_metadata`.
- `services/tasks.py`: `create_task`, `get_task`, `list_tasks`, `list_task_events`, `change_status`, `add_event`,
  `claim_next_task`.
- HTTP: `api/deps.py` (сессия, конфиг, проверка admin-токена), `api/tasks.py` (`POST /tasks`, `GET /tasks/{id}`).
- `settings.py`: `HARNESS_ADMIN_TOKEN` ≥ 32 символов (перенесено из `console-auth` 4.1, D-23).
- `config.py`: сегменты `tokens, secrets, passwd, pwd, credential, credentials`; userinfo в `gitlab.base_url`
  отклоняется (D-26).
- `db/migrations/env.py`: `disable_existing_loggers=False`.

## Capabilities

### New Capabilities

- `task-lifecycle`: задача, её статусы и допустимые переходы, лента событий, очередь задач, HTTP-доступ.

### Modified Capabilities

- `platform-config`: добавлены требования к секретам в конфигурации (расширенные сегменты, userinfo в URL,
  длина `HARNESS_ADMIN_TOKEN`) и к миграциям (логгеры приложения).

## Impact

- Миграция `0001` (первая ревизия; данных ещё нет). ENV `HARNESS_ADMIN_TOKEN` начинает читаться: короткое
  значение теперь не даёт стартовать серверу и worker (fail-fast, D-23). Compose уже передаёт переменную.
- Новых зависимостей нет (UUIDv7 — собственный генератор, D-21).
- Зависит от: `mvp-02-foundation` (принят).
- Ссылки: ТЗ §4, §7, §16.0 п.2, §16.1 A5.
