# Proposal: confirm-second-factor

> Второй фактор для опасных команд. Волна 3 (после MVP), см. PLAN.md.

## Why

Одного chat_id недостаточно: при угоне аккаунта Telegram можно остановить задачи и удалить песочницы (C6).

## What Changes

- TOTP-секрет владельца (хранится зашифрованным), настройка командой CLI
- Опасные команды (`stop_task`, `resume_sandboxes` для всех, `delete_sandbox`) после «Подтвердить» требуют 6-значный код
- Три неверных кода — блокировка опасных команд на 15 минут

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `telegram-bot`: добавляются требования (ADDED): Код для опасных команд.

## Impact

- Зависит от: `control-commands`.
- Ссылки: ТЗ §16.1 C6.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Аппаратные ключи
