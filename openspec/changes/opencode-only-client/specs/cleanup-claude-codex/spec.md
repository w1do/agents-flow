## ADDED Requirements

### Requirement: Удаление Claude Code из bootstrap и сервера

Реализация MUST удалить установку и запуск Claude Code из bootstrap песочницы и кода сервера.
ENV `CLAUDE_CODE_OAUTH_TOKEN` (и live-вариант `LIVE_CLAUDE_CODE_OAUTH_TOKEN`) MUST быть
удалена из кода, тестов и `.env.example`. Функциональные аналоги, нужные задачам (версия CLI,
авторизация, лимит ходов, разбор итога), MUST быть заменены механизмами OpenCode по решению
D-NN, а не только удалены.

#### Scenario: Поиск по коду после реализации

- **WHEN** в `apps/server` и `deploy/` ищут упоминания claude
- **THEN** функциональных упоминаний нет; остаются только исторические документы (`docs/decisions.md`, `openspec/changes/archive/`, `docs/tz/tz-v5.md`)

#### Scenario: Удаляемые места

- **WHEN** изменение реализовано
- **THEN** в bootstrap нет `@anthropic-ai/claude-code`, `--claude-version` и `~/.claude/*`; в сервере нет `CLAUDE_CODE_AGENT_TYPE`, `claude_code_version` и команды `claude -p`

#### Scenario: ENV запуска агента

- **WHEN** worker запускает агента
- **THEN** в env команды нет `CLAUDE_CODE_OAUTH_TOKEN`; авторизация — через ENV OpenCode из D-NN

### Requirement: Удаление Codex

Реализация MUST исключить Codex как тип агента: значение `codex` отклоняется настройками,
упоминания Codex удаляются из рабочих файлов (код, тесты, документация). Изменение
`codex-agent` MUST быть помечено «заменено на OpenCode» и закрыто без реализации.

#### Scenario: Тип codex в настройках

- **WHEN** в `harness.yaml` у workspace указан `agent: codex`
- **THEN** конфигурация отклоняется с понятной ошибкой

#### Scenario: Изменение codex-agent

- **WHEN** после реализации открывают proposal изменения `codex-agent`
- **THEN** видна пометка «заменено на OpenCode (opencode-only-client)», задачи не выполнялись

### Requirement: Рабочая документация без Claude Code и Codex

Рабочие документы — `apps/server/README.md`, `docs/deployment.md`, `docs/README.md`,
`CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `PLAN.md`, `.env.example`,
`config/harness.example.yaml` — MUST не содержать Claude Code и Codex как актуальных
клиентов: команды, флаги, ENV и примеры описывают OpenCode. Исторические документы
(`docs/tz/tz-v5.md`, существующие записи `docs/decisions.md`, `openspec/changes/archive/`)
MUST NOT переписываться; актуальность перехода обеспечивает новая запись D-NN.

#### Scenario: README сервера

- **WHEN** в `apps/server/README.md` читают раздел про bootstrap и live-проверки
- **THEN** флаги, команды и переменные окружения относятся к OpenCode, упоминаний claude/codex нет

#### Scenario: Историческое ТЗ

- **WHEN** открывают `docs/tz/tz-v5.md` с упоминаниями Claude Code/Codex
- **THEN** документ не изменён; действует запись D-NN о переходе на OpenCode

### Requirement: Незакрытые изменения помечаются

Незакрытые OpenSpec-изменения, в артефактах которых есть упоминания Claude Code/Codex,
MUST получить пометку «заменено на OpenCode (opencode-only-client)» в proposal. Изменения
без упоминаний пометок не требуют. Архивные изменения MUST NOT редактироваться.

#### Scenario: Proposal затронутого изменения

- **WHEN** реализация завершена и открыт proposal `integrations-mcp-config`
- **THEN** в нём есть пометка «заменено на OpenCode (opencode-only-client)» о судьбе `ClaudeMcpFormat`

#### Scenario: Полный перечень затронутых

- **WHEN** проверяют пометки после реализации
- **THEN** они стоят в: `agent-sessions`, `cli-version-pin`, `codex-agent`, `integrations-mcp-config`, `mvp-06b-vps-provider`, `mvp-07-agents-flow-mcp`, `mvp-08-spec-planning`, `mvp-09-delivery-mr`, `mvp-10-operator-console`, `sandbox-pool`, `skills-library`, `task-rework`; `sandbox-timeout-extend`, `repo-queue`, `status-commands` упоминаний не содержат (grep 2026-10-22) и не помечаются

#### Scenario: Архив

- **WHEN** ищут упоминания claude/codex в `openspec/changes/archive/`
- **THEN** файлы не изменялись этим изменением

### Requirement: Решение по `.claude/` и `.agents/` подтверждается владельцем

Каталоги `.claude/` (`settings.local.json`, `commands/opsx/*`, `skills/openspec-*`) и
`.agents/` (`skills/openspec-*`) относятся к Claude Code и OpenSpec-skills. Удаление
Claude-специфичных файлов (`settings.local.json`, `commands/opsx` для Claude) выполняется
только после подтверждения владельца; судьба skills (какой каталог читает OpenCode — по
инвентаризации) решается владельцем. До подтверждения файлы MUST оставаться нетронутыми.

#### Scenario: Нет подтверждения

- **WHEN** решение владельца по `.claude/` и `.agents/` не получено
- **THEN** файлы не удаляются и не изменяются

#### Scenario: Подтверждение получено

- **WHEN** владелец подтвердил удаление Claude-специфичных файлов
- **THEN** они удаляются тем же изменением, дифф проходит ревью
