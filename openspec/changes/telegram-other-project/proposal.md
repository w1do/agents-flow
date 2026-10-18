# Proposal: telegram-other-project

> Кнопка «Другой проект». Волна 1 (после MVP), см. PLAN.md.

## Why

Polza показывает до трёх кандидатов, но нужного проекта среди них может не быть. ТЗ §5 требует кнопку «Другой проект» с полным списком.

## What Changes

- Кнопка «Другой проект» под кандидатами
- По нажатию — полный список workspace постранично (по 8 кнопок)
- Выбор из полного списка сохраняется в `routings.chosen_workspace_id` с пометкой `manual`

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `telegram-bot`: добавляются требования (ADDED): Полный список проектов.

## Impact

- Зависит от: `mvp-05-command-routing`.
- Ссылки: ТЗ §5 шаг 3.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Создание нового workspace из Telegram
