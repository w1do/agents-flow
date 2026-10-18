# Proposal: idle-pause

> Пауза простаивающих песочниц. Волна 5 (после MVP), см. PLAN.md.

## Why

Песочница в `active` без работы тратит деньги (C11).

## What Changes

- Счётчик простоя на сервере
- Песочница без задачи дольше `IDLE_PAUSE_MIN` → очистка → пауза

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-runtime`: добавляются требования (ADDED): Автопауза.

## Impact

- Зависит от: `sandbox-pool`.
- Ссылки: ТЗ §16.1 C11.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Удаление простаивающих песочниц
