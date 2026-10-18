# Proposal: db-retention-backups

> Хранение данных и бэкапы. Волна 7 (после MVP), см. PLAN.md.

## Why

База растёт, голосовые файлы не должны жить дольше суток, нужен проверенный бэкап (C7).

## What Changes

- Политика хранения: голосовые — сутки, события и транскрипции — `RETENTION_MONTHS`, чекпоинты — до закрытия задачи + срок
- Ежедневный бэкап Postgres и еженедельная проверка восстановления
- `alembic upgrade` и `alembic check` в CI

## Capabilities

### New Capabilities

- `operations`: хранение данных и бэкапы.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `mvp-09-delivery-mr`.
- Ссылки: ТЗ §15 (позже), §16.1 C7.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Репликация БД
