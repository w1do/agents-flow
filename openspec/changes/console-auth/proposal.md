# Proposal: console-auth

> Консоль: каркас и вход администратора. Волна 6 (после MVP), см. PLAN.md.

## Why

Консоль нужна для настройки и наблюдения; вход — один admin из ENV с хешем в БД (ТЗ §8, preferences).

## What Changes

- `apps/console`: React + shadcn/ui, ESLint + Prettier, README
- `packages/shared-types`: генерация TS-типов из `shared` (JSON Schema)
- Admin из `ADMIN_EMAIL`/`ADMIN_PASSWORD` при первом старте, хеш в БД
- `harness-server reset-password --email --password`
- Сессия консоли выдаёт операторский токен для вызовов MCP
- Сервис `console` в Compose

## Capabilities

### New Capabilities

- `operator-console`: консоль: каркас и вход администратора.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `operator-tokens`.
- Ссылки: ТЗ §8 (вход), §14.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Экраны данных (`console-observability`, `console-settings`)
