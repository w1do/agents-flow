# Proposal: processes

> Процессы в песочнице. Волна 3 (после MVP), см. PLAN.md.

## Why

Сборка, тесты и деплой — долгие процессы; их нужно видеть в консоли и командах (ТЗ §4).

## What Changes

- Таблица `processes` (`running`, `done`, `failed`, время)
- `report_process(name, state)` для агента; гейты сервера пишут процессы сами
- `list_processes` для агента и оператора

## Capabilities

### New Capabilities

- `task-processes`: процессы в песочнице.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `mvp-09-delivery-mr`.
- Ссылки: ТЗ §4 (Process), §11 (`report_process`, `list_processes`).
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Логи процессов целиком
