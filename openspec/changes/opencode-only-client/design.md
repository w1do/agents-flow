# Design: opencode-only-client

Ключевое ограничение этапа: `/home/dev/.config/opencode` недоступен агентам (external
directory, Permission denied; повторная попытка чтения 2026-10-22 отклонена). Содержимое
пользовательской конфигурации неизвестно. Все решения ниже, зависящие от этого содержимого,
опираются на обязательную инвентаризацию (задача 1.1) и не содержат выдуманных имён
переменных, ключей или команд OpenCode.

## Context

Текущее состояние (проверено чтением кода и grep 2026-10-22):

- `deploy/sandbox/bootstrap.sh`: фазы `setup`/`memory`; ставит `@anthropic-ai/claude-code`
  по `--claude-version` (pinned, semver) и `@fission-ai/openspec`; создаёт пустые
  `~/.claude/skills` и `~/.claude/agents` (D-48); пишет статический `~/.harness/mcp.json`
  с литеральными плейсхолдерами `${AGENTS_FLOW_URL}` и `${AGENTS_FLOW_TOKEN}` («Claude Code
  раскрывает их из env»); секреты не пишет в файлы, ключи снимает из env setup-фазы (D-62);
  принцип «удалённый установочный скрипт не запускается» (Node ставится из репозитория
  NodeSource с проверкой gpg).
- `apps/server/src/harness_server/config.py`: `agent: str = "claude-code"`,
  `sandbox.claude_code_version` (semver).
- `apps/server/src/harness_server/settings.py`: `claude_code_oauth_token: SecretStr | None`.
- `apps/server/src/harness_server/worker/dispatcher.py`: передаёт `CLAUDE_CODE_OAUTH_TOKEN`
  в env запуска агента.
- `apps/server/src/harness_server/services/sandboxes.py`: `--claude-version` в аргументы
  bootstrap; `CLAUDE_CODE_AGENT_TYPE`; `run.sh` с `claude -p … --output-format stream-json
  --verbose --max-turns` (D-36/D-37); env с `CLAUDE_CODE_OAUTH_TOKEN`.
- `apps/server/src/harness_server/services/agent_result.py`: разбор события `result`
  потока `stream-json`, распознавание исчерпания лимита подписки Claude (D-54).
- Тесты с упоминаниями (grep): `conftest.py`, `test_sandbox_bootstrap.py`,
  `test_sandbox_service.py`, `test_dispatcher.py`, `test_config.py`, `test_settings.py`,
  `test_agent_result.py`, `test_task_queue.py`, `test_novita_fake.py`, live:
  `test_novita_live.py` (`LIVE_CLAUDE_CODE_OAUTH_TOKEN`), `test_agent_runtime_live.py`,
  `test_sandbox_profile_live.py`.
- Конфиги и документация: `.env.example` (`POLZA_AI_MODEL=anthropic/claude-haiku-5.5`,
  `CLAUDE_CODE_OAUTH_TOKEN`), `config/harness.example.yaml` и `config/harness.yaml`
  (`agent: claude-code`, `claude_code_version`), `apps/server/README.md`,
  `docs/deployment.md`, `docs/README.md`, `ARCHITECTURE.md`, `PLAN.md`, `CLAUDE.md`,
  `AGENTS.md`, `tools/spikes/novita_check.py`.
- Каталоги проекта: `.claude/` (settings.local.json, commands/opsx, skills/openspec-*),
  `.agents/skills/openspec-*` (дубль skills). `.codex/` нет.
- Незакрытые OpenSpec-изменения с упоминаниями claude/codex (grep по `*.md`, без `archive/`):
  agent-sessions, cli-version-pin, codex-agent, integrations-mcp-config,
  mvp-06b-vps-provider, mvp-07-agents-flow-mcp, mvp-08-spec-planning, mvp-09-delivery-mr,
  mvp-10-operator-console, sandbox-pool, skills-library, task-rework.
  Примечание: `sandbox-timeout-extend`, `repo-queue`, `status-commands` упоминаний не
  содержат (grep 2026-10-22 пуст) — в пометках не нуждаются.

## Goals / Non-Goals

**Goals:** один клиент агента — OpenCode; установка закреплённой версией; пользовательская
конфигурация владельца разворачивается в песочницу из версионируемого каталога-источника;
секреты — только плейсхолдеры; удаление Claude Code и Codex из рабочих файлов; документация
обновляется тем же изменением.

**Non-Goals:** поддержка Codex/Junie; реализация в этом этапе (только спецификация);
переписывание исторических документов; автоматическая синхронизация с живым
`~/.config/opencode` (источник фиксируется в репозитории версиями).

## Decisions

### 1. Установка OpenCode через npm с закреплённой версией

Bootstrap ставит OpenCode как глобальный npm-пакет закреплённой версии (semver), флаг
`--opencode-version` вместо `--claude-version`; переиспользуются `ensure_npm_package`
и `npm_global` без изменений их механики (umask 022, идемпотентность).

Точное имя npm-пакета OpenCode и требования к Node закрепляются при инвентаризации/по
официальной документации OpenCode (задача 1.1–1.2), не в этой спеке.

Отвергнутые альтернативы: установка curl-скриптом «через pipe в shell» — нарушает принцип
bootstrap.sh «удалённый установочный скрипт не запускается»; установка без закрепления
версии — дрейф версий ломает формат вывода и флаги (C8, `cli-version-pin`).

### 2. Конфигурация OpenCode из каталога-источника в репозитории

Пользовательская конфигурация владельца один раз переносится из `~/.config/opencode` в
каталог-источник внутри репозитория (предлагается `deploy/sandbox/opencode/`; окончательное
имя — решение D-NN) со следующими правилами:

- секретные значения заменяются плейсхолдерами `{env:NAME}` (значения — только в ENV);
- источник версионируется в git, изменения проходят ревью и тест на отсутствие секретных
  значений;
- bootstrap копирует файлы источника в целевые пути конфигурации OpenCode в песочнице
  (целевые пути закрепляются инвентаризацией), права на каталоги конфигурации — только
  владелец (аналог 700).

Отвергнутые альтернативы: копирование живого `~/.config/opencode` в песочницу напрямую —
секреты уходят на диск песочницы без контроля, нет версионирования, нет ревью; генерация
конфигурации кодом — настройки владельца произвольны, источник истины — его конфигурация,
а не наша схема.

### 3. Секреты: плейсхолдеры и переменные окружения

В файлах источника и развёрнутой конфигурации значений секретов быть не может — только
плейсхолдеры вида `{env:NAME}` (синтаксис подстановки OpenCode подтверждается
инвентаризацией/документацией; для mcp-конфигурации харнесса допускается текущий механизм
`${VAR}` из env, если OpenCode его поддерживает — окончательно в D-NN). Значения передаются
только в env exec-команд (как сейчас `CLAUDE_CODE_OAUTH_TOKEN`, D-18/D-62), проходят
redaction в логах, не пишутся в БД/Telegram/git и не попадают в Memory/RAG.

Отвергнутая альтернатива: хранить значения в конфиге песочницы — прямое нарушение правил
репозитория (секреты не в файлах).

### 4. Единственный тип агента `opencode`

Поле `workspaces[].agent` принимает только `opencode` (значение по умолчанию);
`sandbox.claude_code_version` заменяется полем версии OpenCode; константа
`CLAUDE_CODE_AGENT_TYPE` заменяется на константу OpenCode; команда запуска, env и разбор
итога в `services/sandboxes.py`/`agent_result.py` переводятся на OpenCode. Функциональные
аналоги (лимит ходов, формат потока, авторизация, распознавание исчерпания лимита)
закрепляются D-NN по документации OpenCode; при отсутствии прямого аналога это фиксируется
в D-NN как осознанное упрощение.

Отвергнутая альтернатива: сохранить мульти-клиентскую архитектуру (agent_type как
параметр) — владелец явно хочет один клиент; лишняя абстракция без потребителя.

### 5. Инвентаризация пользовательской конфигурации — обязательный первый шаг

Задача 1.1 выполняется до любых правок кода: владелец (или уполномоченный с доступом)
фиксирует перечень файлов `~/.config/opencode`, ключей и мест подстановки секретов. В
репозиторий и отчёт попадают только имена и плейсхолдеры. Результат закрывает неизвестные:
имя npm-пакета, целевые пути конфигурации, имена ENV авторизации, команды/флаги запуска,
формат вывода.

Отвергнутая альтернатива: написать спеку «по мотивам» документации OpenCode в интернете —
не отражает настройки владельца (задание: «с точно такими же настройками как у меня»), а
несанкционированные догадки о чужой конфигурации запрещены.

### 6. Удаление упоминаний: рабочие файлы чистятся, история не переписывается

Рабочие файлы (код, тесты, README, deployment, `.env.example`, `config/harness.example.yaml`,
`CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `PLAN.md`) очищаются от Claude Code/Codex.
Исторические документы не редактируются: `docs/decisions.md` (существующие ADR D-18, D-36,
D-37, D-46, D-48, D-49, D-54 и др. остаются как история), `docs/tz/tz-v5.md` (ТЗ),
`openspec/changes/archive/`. Актуальность обеспечивает новая запись D-NN («переход на
OpenCode, заменяет D-18/D-36/D-37 в части клиента»).

Отвергнутая альтернатива: править ТЗ и ADR по существу — теряется история решений и
аудит; ADR-лог_append-only по практике проекта (docs/decisions.md — «Решения поверх ТЗ …
обязательны для всех изменений», записи не переписываются).

### 7. Незакрытые OpenSpec-изменения — пометки вместо правки архива

Изменения из Context (12 штук) получают короткую пометку «заменено на OpenCode
(opencode-only-client)» в `proposal.md`; `codex-agent` закрывается без реализации.
Архив не редактируется. Пометка не меняет их сценарии — это фиксация статуса для читателя.

Отвергнутая альтернатива: переписать спеки всех незакрытых изменений под OpenCode —
дублирование работы и риск рассинхронизации с целевой спецификацией этого изменения.

### 8. `.claude/` и `.agents/` — по подтверждению владельца

`.claude/` и `.agents/` относятся к Claude Code и OpenSpec-skills. Предлагаемое решение
(требуется подтверждение владельца, задача 1.3): удалить Claude-специфичные файлы —
`.claude/settings.local.json`, `.claude/commands/opsx/*`; судьбу `.claude/skills/openspec-*`
и дубля `.agents/skills/openspec-*` (какой каталог читает OpenCode — решает инвентаризация
1.1) определяет владелец. До подтверждения ничего не удаляется.

Отвергнутая альтернатива: удалить всё сразу — skills/commands могут использоваться
OpenCode-клиентом (а не только Claude Code), потеря рабочих артефактов владельца.

## Data flow

Bootstrap (фаза setup): Node → npm-пакеты (OpenCode pinned, openspec pinned) → развёртывание
каталога-источника в конфигурацию OpenCode песочницы (плейсхолдеры литеральны) → каталоги
харнесса → mcp-конфиг харнесса → клоны (сервером) → memory (фаза memory). Запуск агента:
worker → exec с env (`AGENTS_FLOW_TOKEN`, `AGENTS_FLOW_URL`, ENV авторизации OpenCode из D-NN;
без `CLAUDE_CODE_OAUTH_TOKEN`) → клиент OpenCode в worktree → файл потока/статуса →
`agent_result` → гейты.

## Security

- Секреты не в репозитории, конфигах, логах, git, БД, Telegram и Memory/RAG; значения только
  в env конкретных exec-команд (правила CLAUDE.md §3, D-18/D-62 сохраняются).
- Каталог-источник проходит тест на отсутствие шаблонов секретов (по образцу
  `test_repo_bootstrap_script_is_executable_and_has_no_secret_values`).
- Redaction сохраняется; значения ENV авторизации добавляются в redaction worker'а.
- Инвентаризация не выносит значений секретов в репозиторий и отчёты.

## Backward compatibility

Изменение ломающее для песочниц с Claude Code: после замены bootstrap повторная подготовка
ставит OpenCode; существующие песочницы перебутстрапливаются вручную (владелец). Конфиг
`harness.yaml` (локальный, не коммитится) обновляется владельцем по примеру. Миграций БД нет.

## Test strategy

- `test_sandbox_bootstrap.py`: новые аргументы (`--opencode-version`), идемпотентность,
  развёртывание источника (файлы записаны, плейсхолдеры литеральны, секретных значений нет),
  отказ от старых флагов, `--help`.
- `test_config.py`/`test_settings.py`: `agent: opencode`, поле версии OpenCode, отклонение
  `claude-code`/`codex`, новые ENV по D-NN.
- `test_sandbox_service.py`/`test_dispatcher.py`/`test_task_queue.py`: команда запуска
  OpenCode, env запуска, отсутствие `CLAUDE_CODE_OAUTH_TOKEN`.
- `test_agent_result.py`: разбор итога OpenCode (формат по D-NN).
- Тест каталога-источника: нет значений секретов.
- Live (`-m live`): `test_novita_live.py`, `test_agent_runtime_live.py`,
  `test_sandbox_profile_live.py` — на OpenCode с его ENV.
- `./tools/harness check` зелёный.

## Rollback

Откат — git revert изменения (код, тесты, документация). Миграций БД нет; песочница
перебутстрапливается старым скриптом из истории git.

## Files allowed to change

- `deploy/sandbox/bootstrap.sh`; новый каталог-источник конфигурации OpenCode (имя по D-NN)
- `apps/server/src/harness_server/`: `config.py`, `settings.py`, `worker/dispatcher.py`,
  `services/sandboxes.py`, `services/agent_result.py`
- `apps/server/tests/`: перечисленные в Context файлы с упоминаниями claude/codex
- `.env.example`, `config/harness.example.yaml`, `config/harness.yaml` (локальный)
- `apps/server/README.md`, `docs/deployment.md`, `docs/README.md`, `docs/decisions.md` (новая
  запись D-NN), `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `PLAN.md`
- `tools/spikes/novita_check.py` (спайк mvp-01: удалить claude-шаги или пометить историческим)
- `openspec/changes/`: этот каталог; пометки «заменено на OpenCode» в proposal незакрытых
  изменений из Context
- `.claude/`, `.agents/` — только после подтверждения владельца (1.3)

## Risks / Trade-offs

- Содержимое `~/.config/opencode` неизвестно: без инвентаризации (1.1) реализация не
  начинается; имена и пути могут не совпасть с предположениями — все неизвестные вынесены
  в D-NN.
- Формат вывода OpenCode может не иметь аналога `stream-json`/`result`: разбор итога и
  распознавание лимитов потребуют отдельной проверки live-тестом (риск MEDIUM).
- Дрейф версий OpenCode: закрепление версией (C8) + обновление отдельной задачей.
- Изменение формата конфигурации OpenCode при мажорных обновлениях: источник
  версионируется, обновление — отдельной задачей.
- Удаление `.claude/` до подтверждения владельца — запрещено (риск потери рабочих
  артефактов).
