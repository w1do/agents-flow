# Tasks

## 1. Инвентаризация и решения (до правок кода)

- [ ] 1.1 Инвентаризация `~/.config/opencode` (выполняет владелец или уполномоченный агент с доступом): перечень файлов, ключей конфигурации и мест подстановки секретов; в репозиторий и отчёт — только имена, ключи и плейсхолдеры `{env:NAME}`, без значений; одновременно подтвердить: имя npm-пакета OpenCode, целевые пути конфигурации в песочнице, имена ENV авторизации, команду/флаги запуска (аналог `--max-turns`), формат вывода (аналог `stream-json`/событие `result`) — файлы: отчёт в MR (без секретов) — проверка: перечень согласован с владельцем, секретных значений нет
- [ ] 1.2 Записать D-NN в `docs/decisions.md`: переход на OpenCode (источник — решение владельца 2026-10-22), канал установки и имя пакета, закреплённая версия, имя каталога-источника, имена ENV авторизации, формат вывода, судьба CLAUDE_CODE_OAUTH_TOKEN — файлы: `docs/decisions.md` — проверка: ревью записи
- [ ] 1.3 Получить решение владельца по `.claude/` и `.agents/`: удаление `.claude/settings.local.json` и `.claude/commands/opsx/*`; судьба `.claude/skills/openspec-*` и дубля `.agents/skills/openspec-*` (какой каталог читает OpenCode — из 1.1) — файлы: ответ владельца в MR — проверка: решение зафиксировано до любых удалений

## 2. Bootstrap песочницы

- [ ] 2.1 `deploy/sandbox/bootstrap.sh`: флаг `--opencode-version` вместо `--claude-version`, установка OpenCode pinned (канал и имя пакета — из D-NN), удаление установки `@anthropic-ai/claude-code`; `--help` и примеры в шапке обновлены — файлы: `deploy/sandbox/bootstrap.sh` — проверка: обновлённые тесты `test_sandbox_bootstrap.py` (аргументы, семвер, идемпотентность, отказ от старого флага, `--help`)
- [ ] 2.2 Создать каталог-источник конфигурации OpenCode (имя из D-NN) с файлами по итогам 1.1 (секреты — только плейсхолдеры `{env:NAME}`) — файлы: каталог-источник — проверка: тест: значений секретов и шаблонов токенов в источнике нет
- [ ] 2.3 `deploy/sandbox/bootstrap.sh`: развёртывание каталога-источника в конфигурацию OpenCode песочницы (целевые пути из D-NN, права доступа только владельцу, идемпотентно) — файлы: `deploy/sandbox/bootstrap.sh` — проверка: тест: файлы конфигурации записаны, плейсхолдеры литеральны, повторный запуск не ломает
- [ ] 2.4 `deploy/sandbox/bootstrap.sh`: заменить `~/.claude/{skills,agents}` и статический `~/.harness/mcp.json` на пути/формат OpenCode (по D-NN; mcp-плейсхолдеры `AGENTS_FLOW_URL`/`AGENTS_FLOW_TOKEN` сохраняются с синтаксисом по D-NN) — файлы: `deploy/sandbox/bootstrap.sh` — проверка: тесты `test_sandbox_bootstrap.py` (mcp-конфиг записан, без значений секретов)

## 3. Сервер: агент OpenCode

- [ ] 3.1 `config.py`: `agent` — только `opencode` (значение по умолчанию, отклонение остальных), `sandbox.opencode_version` вместо `claude_code_version` — файлы: `apps/server/src/harness_server/config.py` — проверка: `test_config.py`
- [ ] 3.2 `settings.py`: удалить `claude_code_oauth_token`, добавить ENV авторизации OpenCode (имена из D-NN) — файлы: `apps/server/src/harness_server/settings.py` — проверка: `test_settings.py`
- [ ] 3.3 `services/sandboxes.py`: константа агента OpenCode вместо `CLAUDE_CODE_AGENT_TYPE`, аргументы bootstrap (`--opencode-version`), `run.sh` с командой OpenCode (флаги из D-NN), env запуска без `CLAUDE_CODE_OAUTH_TOKEN` — файлы: `apps/server/src/harness_server/services/sandboxes.py` — проверка: `test_sandbox_service.py`
- [ ] 3.4 `services/agent_result.py`: разбор итога OpenCode (формат из D-NN; распознавание исчерпания лимита, если применимо) — файлы: `apps/server/src/harness_server/services/agent_result.py` — проверка: `test_agent_result.py`
- [ ] 3.5 `worker/dispatcher.py`: env авторизации OpenCode вместо `CLAUDE_CODE_OAUTH_TOKEN`; значения в redaction — файлы: `apps/server/src/harness_server/worker/dispatcher.py` — проверка: `test_dispatcher.py`

## 4. Cleanup упоминаний Claude Code и Codex

- [ ] 4.1 `.env.example`: удалить блок `CLAUDE_CODE_OAUTH_TOKEN` (только имя, без значения); обновить комментарий к `POLZA_AI_MODEL` (модель классификации не привязана к клиенту агента; пример значения `anthropic/claude-haiku-5.5` заменить, если решение D-NN требует) — файлы: `.env.example` — проверка: grep по `.env.example` без claude/codex
- [ ] 4.2 `config/harness.example.yaml` и `config/harness.yaml`: `agent: opencode`, поле версии OpenCode — файлы: `config/harness.example.yaml`, `config/harness.yaml` (локальный) — проверка: `test_config.py`, ревью
- [ ] 4.3 Тесты: убрать `CLAUDE_CODE_OAUTH_TOKEN`, `claude`, `claude-code` из `conftest.py`, `test_task_queue.py`, `test_novita_fake.py` и остальных по grep — файлы: `apps/server/tests/` — проверка: `grep -riE 'claude|codex' apps/server` — пусто
- [ ] 4.4 Live-тесты: `test_novita_live.py`, `test_agent_runtime_live.py`, `test_sandbox_profile_live.py` — на OpenCode, live-переменные переименованы (имена из D-NN), сценарии изоляции адаптированы к OpenCode — файлы: live-тесты — проверка: прогон `-m live` владельцем, результат в MR
- [ ] 4.5 Документация: `apps/server/README.md`, `docs/deployment.md`, `docs/README.md`, `CLAUDE.md`, `AGENTS.md` — без Claude Code/Codex как актуальных клиентов — файлы: перечисленные — проверка: grep + ревью
- [ ] 4.6 `tools/spikes/novita_check.py`: удалить claude-шаги или пометить спайк историческим (решение в D-NN) — файлы: `tools/spikes/novita_check.py` — проверка: ревью
- [ ] 4.7 `.claude/` и `.agents/`: выполнить решение владельца из 1.3 — файлы: `.claude/`, `.agents/` — проверка: ревью диффа, решение 1.3 приложено

## 5. OpenSpec-изменения: пометки «заменено на OpenCode»

- [ ] 5.1 Добавить пометку «заменено на OpenCode (opencode-only-client)» в proposal незакрытых изменений с упоминаниями: agent-sessions, cli-version-pin, codex-agent, integrations-mcp-config, mvp-06b-vps-provider, mvp-07-agents-flow-mcp, mvp-08-spec-planning, mvp-09-delivery-mr, mvp-10-operator-console, sandbox-pool, skills-library, task-rework; `codex-agent` закрыть без реализации; архив не редактировать — файлы: `openspec/changes/<id>/proposal.md` — проверка: `openspec list`, ревью

## 6. Документация (тем же изменением)

- [ ] 6.1 Обновить `ARCHITECTURE.md` (компоненты, bootstrap, таблица ENV §9 — без `CLAUDE_CODE_OAUTH_TOKEN`, с ENV OpenCode), `PLAN.md` (статус этого изменения и `codex-agent`) — файлы: `ARCHITECTURE.md`, `PLAN.md` — проверка: ревью диффа документации

## 7. Проверки

- [ ] 7.1 Прогнать `./tools/harness check` (ruff, ruff format --check, mypy --strict, pytest) — проверка: зелёный вывод команды приложен к MR

## 8. Память проекта

- [ ] 8.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов — проверка: `memory_status`
