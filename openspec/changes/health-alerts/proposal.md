# Proposal: health-alerts

> Внешний healthcheck и «жив». Волна 7 (после MVP), см. PLAN.md.

## Why

Падение харнесса должен кто-то заметить (C9).

## What Changes

- Внешний uptime-сервис опрашивает `/health/ready` и пишет в Telegram при тишине
- Бот раз в сутки отправляет «жив» со сводкой (задачи, песочницы)

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `operations`: добавляются требования (ADDED): Ежедневный сигнал.

## Impact

- Зависит от: `mvp-04-telegram-intake`.
- Ссылки: ТЗ §16.1 C9.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Метрики и дашборды
