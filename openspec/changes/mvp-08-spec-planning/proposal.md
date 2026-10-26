# Proposal: mvp-08-spec-planning

## Why

Работа всегда начинается со спецификации, даже для мелкой правки (ТЗ §5.0 класс 1). Планировщик в песочнице пишет
OpenSpec-изменение, раскладывает его на задачи `implement` в `backlog`, а владелец получает итог «спецификация
готова, задач: N» (ТЗ §6, §10.1, §16.0 п.3).

## What Changes

- Пайплайн `plan` в worker: `planning` → активация песочницы (база `origin/<default_branch>`, ветка `task/<plan_id>`)
  → запуск планировщика → проверки сервера → push ветки плана → `ready` → очистка → пауза.
- Промпт планировщика `services/prompts/planner.md`: задача, workspace, правила OpenSpec (создать изменение через
  `openspec new change`, proposal/design/specs/tasks, `openspec validate`), декомпозиция на пункты, вызовы
  `sync_spec` и `create_task` по каждому пункту, `report_task("completed")`, коммит в ветку.
- Проверки сервера после планировщика: в ветке есть новый каталог `openspec/changes/<id>/`, `openspec validate <id>`
  проходит, есть хотя бы одна задача `implement`, фильтр секретов по diff, push (идемпотентно).
- Итог в Telegram: строка «спецификация готова, задач: N» и список задач (краткие названия).
- Модуль `worker/gates.py` с первыми гейтами: `secret_scan`, `push` (используются и в `mvp-09`).
- Минимальный MCP планировщика на `/mcp`: авторизация токеном задачи, `sync_spec`, `create_task`,
  `report_task`, `list_tasks`; реализации отсутствующих зависимостей входят в это изменение
  по решению оркестратора от 2026-10-26. Другие changes не меняются.
- Worker API состояния плана и его дочерних задач и идемпотентного завершения: отказ атомарно
  переводит план в `error`, его задачи `implement` в `trash`; успех фиксирует ветку и `ready`.

## Capabilities

### New Capabilities

- `spec-planning`: планирование работы через OpenSpec и раскладка в задачи реализации.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `mvp-05-command-routing`, `mvp-06-sandbox-runtime`, `mvp-07-agents-flow-mcp`.
- В репозитории workspace появляются каталоги `openspec/changes/<id>/` в ветке `task/<plan_id>`.
- Ссылки: ТЗ §5.0, §6 (этапы plan), §10.1 (спецификация), §16.0 п.3, §16.1 A3.

## Не входит

Утверждение спецификации кнопкой (`spec-approval`), расхождение файла и зеркала (`spec-drift`), отдельный MR для
плана (D-10).
