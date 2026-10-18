# Proposal: status-commands

> Команды статуса. Волна 3 (после MVP), см. PLAN.md.

## Why

Кроме списка задач владелец спрашивает «что делает агент» и «сколько потрачено». ТЗ §6 требует отвечать на них из `agents-flow` и ленты событий.

## What Changes

- Подтипы класса `status`: `tasks`, `agent`, `spend`
- «Что делает агент» — последние события активных задач
- «Сколько потрачено» — `usage(period)`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `command-routing`: добавляются требования (ADDED): Ответы на вопросы о состоянии.

## Impact

- Зависит от: `mvp-05-command-routing`, `budget-usage`.
- Ссылки: ТЗ §5.0 класс 3, §6 (команды статуса).
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Управляющие действия (`control-commands`)
