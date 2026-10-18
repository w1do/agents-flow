# Proposal: revert-task

> Откат влитой задачи. Волна 4 (после MVP), см. PLAN.md.

## Why

Каждый мердж должен откатываться одной командой (B4).

## What Changes

- Регистрация каждого мерджа (задача, коммит, ветка)
- Инструмент `revert_task(task_id, confirm)`: revert-коммит в новой ветке, те же гейты, MR

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `delivery-gates`: добавляются требования (ADDED): Откат через те же гейты.

## Impact

- Зависит от: `staging-auto-merge`.
- Ссылки: ТЗ §16.1 B4.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Откат миграций БД продукта
