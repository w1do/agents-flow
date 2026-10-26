# Proposal: opencode-only-client

> **Частичная замена:** `local-agent-machine` отменяет только будущие задачи 1.3, 2.1–2.4 и 3.1,
> относящиеся к каталогу-источнику конфигурации, deploy/bootstrap/install, закреплению версии и
> полю версии в конфигурации. Инвентаризация клиента, запуск, результат, auth ENV, переход на
> OpenCode и cleanup Claude/Codex остаются будущим объёмом этого изменения; текущий runtime ещё
> не является runtime OpenCode.

> Единственный клиент агента — OpenCode: полный переход с Claude Code, Codex не вводится.
> Bootstrap ставит OpenCode с настройками владельца. Решение владельца 2026-10-22.

## Why

Владелец полностью переходит на OpenCode: клиент агента больше не Claude Code, Codex не будет.
Bootstrap песочницы должен ставить OpenCode «со всеми моими настройками» — источник настроек:
пользовательская конфигурация владельца `~/.config/opencode`. Всё, что было связано с
Claude Code и Codex, удаляется из кода, конфигов, тестов и документации.

Ограничение (подтверждено на этапе спецификации): каталог `/home/dev/.config/opencode`
недоступен агентам для чтения (external directory, Permission denied). Содержимое на момент
спецификации неизвестно. Точные файлы, ключи конфигурации, имена ENV и команды OpenCode
определяются обязательной инвентаризацией (задача 1.1) и в этой спецификации не выдумываются.

## What Changes

- Bootstrap песочницы (`deploy/sandbox/bootstrap.sh`) ставит OpenCode закреплённой версией
  вместо `@anthropic-ai/claude-code`; флаг `--claude-version` заменяется флагом версии OpenCode.
- В репозитории появляется каталог-источник шаблона пользовательской конфигурации OpenCode
  (имя закрепляется решением D-NN); bootstrap разворачивает его в песочницу. Наполняется
  источник только по итогам инвентаризации `~/.config/opencode` (задача 1.1).
- Секретные значения в конфигурации — только плейсхолдеры `{env:NAME}` или переменные
  окружения; значения никогда не попадают в репозиторий, логи и память (Memory/RAG).
- Тип агента в настройках — только `opencode`; `sandbox.claude_code_version` заменяется
  версией OpenCode; команда запуска, разбор итога и env запуска агента переводятся с
  `claude -p` на OpenCode.
- ENV `CLAUDE_CODE_OAUTH_TOKEN` удаляется (в спеке — только имя переменной); авторизация
  OpenCode — через переменные окружения, имена фиксируются инвентаризацией.
- Удаляются упоминания Claude Code и Codex из кода сервера, тестов, README частей,
  deployment-документации, `.env.example`, `config/harness.example.yaml`, `CLAUDE.md`,
  `AGENTS.md`, `ARCHITECTURE.md`, `PLAN.md` (документация обновляется тем же изменением
  при реализации).
- Незакрытые OpenSpec-изменения с упоминаниями Claude Code/Codex помечаются «заменено на
  OpenCode»; архивные изменения не редактируются.

## Capabilities

### New Capabilities

- `opencode-client`: установка OpenCode закреплённой версией, инвентаризация пользовательской
  конфигурации, развёртывание конфигурации из каталога-источника, секреты только плейсхолдерами,
  OpenCode как единственный клиент агента.
- `cleanup-claude-codex`: удаление и замена упоминаний Claude Code и Codex в коде, тестах,
  конфигурации и документации.

### Modified Capabilities

Нет: целевое состояние описывают новые возможности. Существующие требования о Claude Code
в `sandbox-runtime` и `sandbox-profile` (установка, запуск, изоляция, mcp.json) при реализации
этого изменения переводятся на OpenCode; после архивирования обновляются в `openspec/specs/`.

## Impact

- Ссылки: ТЗ §5.0 (вопрос 16 — теперь OpenCode с OpenSpec), §12, §16 п.9 (типы агентов),
  §17 вопросы 13 и 16, ограничение C8 (версии CLI закрепляются). Переход на OpenCode — решение
  владельца поверх ТЗ: фиксируется новой записью D-NN в `docs/decisions.md` при реализации.
- Зависимости: закрывает `codex-agent` (второй агент не вводится); затрагивает `agent-sessions`,
  `cli-version-pin`, `integrations-mcp-config`, `skills-library`, `sandbox-pool`, `task-rework`,
  `mvp-06b-vps-provider`, `mvp-07-agents-flow-mcp`, `mvp-08-spec-planning`, `mvp-09-delivery-mr`,
  `mvp-10-operator-console` (полный перечень — в cleanup-спеке).
- Затрагивает: `deploy/sandbox/bootstrap.sh`; `apps/server` (`config.py`, `settings.py`,
  `worker/dispatcher.py`, `services/sandboxes.py`, `services/agent_result.py`); тесты
  (`conftest.py`, `test_sandbox_bootstrap.py`, `test_sandbox_service.py`, `test_dispatcher.py`,
  `test_config.py`, `test_settings.py`, `test_agent_result.py`, `test_task_queue.py`,
  `test_novita_fake.py`, live-тесты); `.env.example`; `config/harness.example.yaml`;
  `apps/server/README.md`; `docs/deployment.md`; `docs/README.md`; `CLAUDE.md`; `AGENTS.md`;
  `ARCHITECTURE.md`; `PLAN.md`; `tools/spikes/novita_check.py`; каталоги `.claude/`, `.agents/`
  (по подтверждению владельца).
- Риски: содержимое `~/.config/opencode` неизвестно (обязательна инвентаризация); дрейф версий
  OpenCode (закрепление версией, C8); формат вывода и флаги OpenCode отличаются от
  `claude -p` (проверяется live-тестом); изменение формата конфигурации OpenCode при обновлениях.

## Не входит

- Реализация кода на этом этапе: создаётся только спецификация; реализация — по `tasks.md`.
- Поддержка других клиентов: Codex (изменение `codex-agent` закрывается как «заменено на
  OpenCode»), Junie.
- Наполнение каталога-источника реальными настройками до инвентаризации (1.1).
- Правка архивных изменений `openspec/changes/archive/` и переписывание истории
  `docs/decisions.md` (существующие ADR не редактируются; переход фиксируется новой записью).
- Правка `docs/tz/tz-v5.md`: ТЗ — исторический документ требований; актуальность перехода на
  OpenCode обеспечивает запись D-NN (см. design, решение 6).
