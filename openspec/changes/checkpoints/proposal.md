# Proposal: checkpoints

> Чекпоинты агента. Волна 3 (после MVP), см. PLAN.md.

## Why

Без чекпоинтов нельзя продолжить задачу после паузы или срыва (ТЗ §10 п.5).

## What Changes

- Инструмент `save_checkpoint(summary, next_step, files)` для агента
- Запасной чекпоинт сервера: список файлов и статистика diff через exec, если агент не сохранил
- Операторские `list_checkpoints`, `get_checkpoint`
- Кнопка «Показать чекпоинт» в Telegram

## Capabilities

### New Capabilities

- `agent-checkpoints`: чекпоинты агента.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `mvp-09-delivery-mr`.
- Ссылки: ТЗ §10 п.5, §10.1 (чекпоинт сессии), §11.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Полный diff в БД: хранится хеш коммита (ТЗ §10.1)
