# Proposal: sandbox-profile

> Версионируемый профиль песочницы. Волна 5 (после MVP), см. PLAN.md.

## Why

Песочницы должны собираться из одного версионируемого профиля, а не вручную (ТЗ §13).

## What Changes

- Таблица `sandbox_profiles` с версиями: предпочтения, память, конфиги агентов, MCP, skills, репозитории, версия bootstrap
- `GET /bootstrap/{profile_id}.sh` по одноразовому токену
- Генерация `CLAUDE.md` и `AGENTS.md` из предпочтений
- `get_profile`, `update_profile` (новая версия), `get_bootstrap_link`

## Capabilities

### New Capabilities

- `sandbox-profile`: версионируемый профиль песочницы.

### Modified Capabilities

Нет.

## Impact

- Зависит от: `sandbox-pool`.
- Ссылки: ТЗ §9 (создание одной командой), §13, §7 (`GET /bootstrap`), §17 вопрос 4.
- Затрагивает ARCHITECTURE.md (разделы по теме) и, при новых инструментах, docs/mcp-agents-flow.md.

## Не входит

- Кастомные образы Novita (вопрос 6)
