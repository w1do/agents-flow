# Proposal: budget-usage

> Учёт расхода токенов. Волна 3 (после MVP), см. PLAN.md.

## Why

Нужно знать, сколько стоит каждая задача и период (ТЗ §16 п.8).

## What Changes

- Разбор события `result` из `stream.jsonl`: usage и `total_cost_usd`
- Таблица `usage_records` (задача, сессия, токены, стоимость)
- Инструмент `usage(period)`

## Capabilities

### New Capabilities

- `budget`: учёт расхода токенов.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `mvp-09-delivery-mr`.
- Ссылки: ТЗ §10 п.3, §11 (`usage`), §16 п.8.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Остановка по бюджету (`task-limits`)
