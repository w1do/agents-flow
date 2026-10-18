# Proposal: staging-auto-merge

> Авто-мердж через staging. Волна 4 (после MVP), см. PLAN.md.

## Why

Ручной мердж — страховка среза. После накопления статистики мердж делается автоматически, но сначала в staging (B5, preferences).

## What Changes

- Режим workspace `merge_mode`: `manual` (по умолчанию), `staging`, `main`
- Авто-мердж только после всех зелёных гейтов
- Переход на `main` — отдельная настройка с подтверждением
- Статус `merged` и этап «влита MR» (вебхук GitLab или опрос)

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `delivery-gates`: добавляются требования (ADDED): Мердж только после зелёных гейтов.

## Impact

- Зависит от: `gates-tests-deploy`.
- Ссылки: ТЗ §6 (влита MR), §16.1 B5, §17 вопрос 10.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Откат (`revert-task`)
