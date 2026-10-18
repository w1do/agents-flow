# Proposal: gates-tests-deploy

> Гейты тестов и деплоя по workspace. Волна 4 (после MVP), см. PLAN.md.

## Why

Разные workspace требуют разных гейтов: тексты — только коммит и пуш, продукт — тесты и деплой (ТЗ §12).

## What Changes

- Список гейтов в конфиге workspace (`commit`, `secrets`, `tests`, `deploy`, `mr`, `merge`)
- Гейт `deploy`: команда деплоя в staging, код возврата
- Тесты — отдельный процесс с отчётом в Telegram (этап «тестирование»)

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `delivery-gates`: добавляются требования (ADDED): Гейты задаются workspace, Гейт деплоя.

## Impact

- Зависит от: `processes`.
- Ссылки: ТЗ §10 п.4, §12 (гейты workspace).
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Авто-мердж (`staging-auto-merge`)
