# Proposal: workspace-settings-snapshot

> Фиксация настроек workspace на старте задачи. Волна 6 (после MVP), см. PLAN.md.

## Why

Изменение workspace во время задачи не должно менять её поведение (C12).

## What Changes

- Задача хранит снимок настроек workspace (версию) на момент старта
- Пайплайн читает настройки из снимка

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `task-lifecycle`: добавляются требования (ADDED): Настройки задачи неизменны.

## Impact

- Зависит от: `console-settings`.
- Ссылки: ТЗ §16.1 C12.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Миграция активных задач на новые настройки
