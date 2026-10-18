# Proposal: console-observability

> Консоль: канбан и наблюдаемость. Волна 6 (после MVP), см. PLAN.md.

## Why

Канбан, задачи, события, чекпоинты и решения Polza нужно видеть не только в Telegram (ТЗ §8).

## What Changes

- Канбан по статусам задач
- Карточка задачи: события, чекпоинты, процессы, MR, решение маршрутизации
- Расход токенов
- Только чтение через инструменты MCP

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `operator-console`: добавляются требования (ADDED): Только чтение через MCP.

## Impact

- Зависит от: `console-auth`, `mcp-operator-tools`.
- Ссылки: ТЗ §8 (наблюдаемость).
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Правки задач из консоли
