# Proposal: dry-run

> Тестовый прогон workspace. Волна 4 (после MVP), см. PLAN.md.

## Why

Новый workspace нужно проверить всем путём без реального пуша в боевой репозиторий (C10).

## What Changes

- Команда `dry_run(workspace)`: весь путь на тестовом репозитории
- Push только в тестовый репозиторий, мердж не выполняется
- Workspace без успешного dry-run не принимает задачи

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `delivery-gates`: добавляются требования (ADDED): Dry-run обязателен.

## Impact

- Зависит от: `gates-tests-deploy`.
- Ссылки: ТЗ §16.1 C10.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Нагрузочные прогоны
