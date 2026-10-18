# Tasks

## 1. Реализация

- [ ] 1.1 `deploy/sandbox/harness-snap` (bash, set -euo pipefail) — проверка: shellcheck и тест в песочнице
- [ ] 1.2 Планировщик снимков в worker — проверка: тест с фейком
- [ ] 1.3 Модель и миграция `snapshots` — проверка: alembic

## 2. Документация

- [ ] 2.1 Обновить ARCHITECTURE.md (затронутые разделы, таблицы, ENV), docs/mcp-agents-flow.md при новых инструментах, docs/decisions.md при новых решениях, PLAN.md — проверка: ревью диффа документации

## 3. Память проекта

- [ ] 3.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов
