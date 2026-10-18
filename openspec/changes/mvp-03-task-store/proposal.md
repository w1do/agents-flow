# Proposal: mvp-03-task-store

## Why

Postgres — единственный источник правды (ТЗ §2 п.7). Telegram, MCP и worker должны работать с одной моделью
задачи и одними правилами смены статуса, иначе канбан и сообщения разойдутся. Это изменение даёт схему,
машину статусов и сервис задач, на которые опираются все следующие изменения (ТЗ §4, §16.0 п.2).

## What Changes

- Перечисления и DTO в `shared`: `TaskKind`, `TaskStatus` (12 статусов ТЗ v5), `TaskSource`, `TestsState`, `TaskOut`, `TaskEventOut`.
- `domain/statuses.py`: таблица допустимых переходов для `plan` и `implement`, `InvalidTransition`.
- ORM-модели и первая миграция: `tasks`, `task_events`, `routings`, `spec_items`, `sandboxes`, `checkpoints`,
  `telegram_messages`, `telegram_updates`, `task_tokens` (ARCHITECTURE.md §3).
- `services/tasks.py`: создание задачи, смена статуса с записью `TaskEvent`, выбор следующей задачи
  из очереди (`FOR UPDATE SKIP LOCKED`, приоритет, затем время), список задач workspace.
- HTTP: `POST /tasks` и `GET /tasks/{id}` под временным операторским bearer `HARNESS_ADMIN_TOKEN`.

## Capabilities

### New Capabilities

- `task-lifecycle`: задача, её статусы и допустимые переходы, лента событий, очередь задач.

### Modified Capabilities

Нет.

## Impact

- Миграция `0001_initial`. Новая ENV `HARNESS_ADMIN_TOKEN` (ARCHITECTURE.md §9, `.env.example`).
- Зависит от: `mvp-02-foundation`.
- Ссылки: ТЗ §4, §7, §16.1 A5.

## Не входит

`Process`, `sessions`, таблицы настроек (workspace, skills и т.д.) — после MVP. Операторские токены — `operator-tokens`.
