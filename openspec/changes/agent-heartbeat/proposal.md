# Proposal: agent-heartbeat

> Heartbeat агента и статус stalled. Волна 3 (после MVP), см. PLAN.md.

## Why

Зависший агент должен обнаруживаться автоматически (C2).

## What Changes

- Инструмент `heartbeat` и обёртка запуска, отправляющая его раз в минуту
- Нет heartbeat 5 минут → проверка песочницы через exec → `stalled` при отсутствии процесса
- Переходы `active→stalled`, `stalled→active|error`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-runtime`: добавляются требования (ADDED): Обнаружение зависания.

## Impact

- Зависит от: `mvp-07-agents-flow-mcp`.
- Ссылки: ТЗ §16.1 C2.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Перенос на другую песочницу (`stalled-reassign`)
