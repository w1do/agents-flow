# Proposal: harness-snap

> Снимки работы раз в минуту. Волна 3 (после MVP), см. PLAN.md.

## Why

При потере песочницы должно теряться не больше минуты работы (ТЗ §10.1, C1).

## What Changes

- Скрипт `harness-snap` ставится bootstrap-скриптом
- Сервер раз в минуту вызывает его через exec: фильтр секретов, WIP-коммит в `task/<id>`, push
- Таблица `snapshots`: хеш коммита, число файлов, время

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `agent-checkpoints`: добавляются требования (ADDED): Периодический снимок.

## Impact

- Зависит от: `checkpoints`.
- Ссылки: ТЗ §10.1 (снимок), §16.1 C1.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Diff в БД
