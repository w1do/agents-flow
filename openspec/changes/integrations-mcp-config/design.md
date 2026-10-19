# Design: integrations-mcp-config

Решения — D-46 (и D-45 про vault). Открытые вопросы — в `proposal.md`.

## Context

После `sandbox-profile`: `harness_server/vault_ref.py` (`VaultRef`, `parse_vault_ref`, `is_vault_ref`),
`adapters/vault` (`SecretVault`, `FakeVault`, `VaultError`), `services/secrets.resolve`, `DispatchContext.vault`,
`sandboxes.run_agent(..., extra_envs=)` и `HARNESS_MEMORY_PROJECT` в env агента, `config.sandbox.memory`
(`version`, `embedding_ref`). `run.sh` запускает `claude -p … --strict-mcp-config --mcp-config "$HOME/.harness/mcp.json"
--setting-sources user` (D-36). Bootstrap пишет статический `~/.harness/mcp.json` с одним `agents-flow`.
Модели ORM — `apps/server/src/harness_server/db/models/*.py`, миграции — `db/migrations/versions/` (корень репозитория), последняя `20261019_0004_sandbox_agent_run.py`.
Перечисления в БД — `VARCHAR(16)` + CHECK (D-22), id — `uuid7()` (D-21), сервис — одна транзакция с commit (D-24).

## Goals / Non-Goals

**Goals:** оператор ведёт список MCP-серверов на платформе; агент получает их при каждом запуске; ключи только из vault
и только в env; изоляция от `.mcp.json` репозитория сохранена.

**Non-Goals:** интеграции CRM; MCP-инструменты раздела; привязка к workspace; консоль; форматы Codex и Junie.

## Decisions

### 1. Таблица `mcp_servers` (миграция `0005`)

Файл `db/migrations/versions/<YYYYMMDD>_0005_mcp_servers.py` (дата реализации), модель `McpServer` в новом
`db/models/mcp.py`, экспорт в `db/models/__init__.py`.

| Колонка | Тип | Правило |
|---|---|---|
| `id` | UUID PK | `uuid7()` |
| `name` | VARCHAR(64) NOT NULL UNIQUE (`uq_mcp_servers_name`) | `^[a-z0-9][a-z0-9_-]{0,63}$`, не `agents-flow`, не `project-memory` |
| `description` | TEXT NOT NULL DEFAULT `''` | |
| `transport` | VARCHAR(16) NOT NULL, CHECK `ck_mcp_servers_transport` | `http`, `sse`, `stdio` |
| `url` | TEXT NULL | `http`/`sse`: обязателен, `https://`; `stdio`: NULL |
| `command` | TEXT NULL | `stdio`: обязателен; иначе NULL |
| `args` | JSONB NOT NULL DEFAULT `[]` | список строк, только `stdio` |
| `env` | JSONB NOT NULL DEFAULT `{}` | ключ `^[A-Z_][A-Z0-9_]{0,63}$` → значение |
| `headers` | JSONB NOT NULL DEFAULT `{}` | имя заголовка `^[A-Za-z0-9-]{1,64}$` → значение; только `http`/`sse` |
| `created_at`, `updated_at` | TIMESTAMPTZ | `TimestampMixin` |

Enum `McpTransport` — в `harness_shared/mcp.py` (значения видит консоль позже); в миграции значения литералами (D-22).

Раздел глобальный: в ТЗ `get_mcp_config` по workspace, но у владельца один набор серверов (vault, preferences) для всех
проектов, а MCP-инструментов в этом изменении нет. Привязка добавится отдельной таблицей без изменения этой.

### 2. Значения и ссылки на vault

- Значение `env`/`headers` — строка без перевода строки и NUL, до 4096 символов. Ссылка:
  `VALUE_REF_RE = re.compile(r"^(?P<prefix>(?:\S+ )?)(?P<ref>vault:\S.*)$")`, затем `parse_vault_ref(ref)` — не `None`.
  Примеры: `vault:Песочница/vault/agent`, `Bearer vault:Песочница/vault/agent`.
- Литеральный секрет отклоняется: заголовки `authorization`, `proxy-authorization`, `x-api-key`, `api-key` (без учёта
  регистра) и ключи `env` с сегментами `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `APIKEY` (разбиение по `_`) обязаны быть
  ссылками. В `url`, `command`, `args` ссылки и `${` запрещены.
- В БД хранится введённая строка (ссылка — не секрет). Чтение (`list`, `show`) возвращает её как есть.

### 3. Сервис `services/mcp_servers.py`

Pydantic-модель входа `McpServerInput` (в `harness_shared/mcp.py`, её увидит консоль): `name`, `description: str = ""`,
`transport`, `url`, `command`, `args: list[str] = []`, `env: dict[str, str] = {}`, `headers: dict[str, str] = {}`,
`extra="forbid"`, валидаторы п. 1–2. Выход `McpServerView` — те же поля + `id`, `updated_at`.

Функции (одна транзакция, D-24; docstring):

- `async add_server(session, data: McpServerInput, *, replace: bool = False) -> McpServerView` — нет записи → INSERT;
  есть и `replace` → UPDATE всех полей; есть без `replace` → `McpServerExists(name)`.
- `async list_servers(session) -> list[McpServerView]` — по `name`.
- `async get_server(session, name) -> McpServerView` — нет → `McpServerNotFound(name)`.
- `async remove_server(session, name) -> None` — нет → `McpServerNotFound`.
- `async build_agent_config(session, vault, *, memory: SandboxMemoryConfig | None, fmt: McpConfigFormat) ->
  AgentMcpConfig` — читает все записи, разворачивает ссылки (`vault.get`, по одному запросу на ссылку, без
  повторов одной и той же ссылки), строит `AgentMcpConfig(content: str, envs: dict[str, SecretStr])`:
  - каждое значение-ссылка `i`-го сервера (порядок по `name`), `j`-го значения (порядок: `env` по ключу, затем
    `headers` по имени) заменяется на `prefix + "${HARNESS_MCP_<i>_<j>}"`, а `envs["HARNESS_MCP_<i>_<j>"]` = значение;
  - если `memory` задан — встроенный сервер `project-memory`: stdio, `command="memory"`,
    `args=["mcp", "--project", "${HARNESS_MEMORY_PROJECT}"]`, `env={"EMBEDDING_API_KEY": "${HARNESS_MEMORY_EMBEDDING}"}`
    при `memory.embedding_ref` и `envs["HARNESS_MEMORY_EMBEDDING"]` = значение из vault;
  - `agents-flow`: http, `url="${AGENTS_FLOW_URL}"`, `headers={"Authorization": "Bearer ${AGENTS_FLOW_TOKEN}"}`;
  - `content = fmt.render(servers)`.
  Ссылка без vault → `VaultError("not_configured")`.

Исключения `McpServerExists`, `McpServerNotFound` — подклассы `DomainError` в `domain/errors.py`.

### 4. Адаптер формата

`services/mcp_formats.py`:

- `@dataclass(frozen=True) class RenderedServer: name: str; transport: str; url: str | None; command: str | None;
  args: list[str]; env: dict[str, str]; headers: dict[str, str]` (значения уже с плейсхолдерами).
- `class McpConfigFormat(Protocol): agent_type: str; def config_path(self, home: str) -> str: ...;
  def render(self, servers: Sequence[RenderedServer]) -> str: ...`.
- `ClaudeMcpFormat` (`agent_type = "claude-code"`): путь `<home>/.harness/mcp.json`; JSON
  `{"mcpServers": {name: {"type": transport, "url", "headers"} | {"type": "stdio", "command", "args", "env"}}}`, ключи
  без `None`, `json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True)`.
- `FORMATS: dict[str, McpConfigFormat] = {"claude-code": ClaudeMcpFormat()}`; Codex (`config.toml`) и Junie — не
  реализуются, `format_for(agent_type)` для неизвестного типа → `KeyError` с понятным текстом.

### 5. Запуск агента (изменение `sandbox-runtime`, D-46)

- `sandboxes.run_agent(...)` — новый kw-параметр `mcp_config: str | None = None`. Если задан — до записи `run.sh`:
  `write_file(<home>/.harness/mcp.json, mcp_config)` и `chmod 600` (через `_exec_ok`, reason `mcp_config`). Файл без
  значений — только плейсхолдеры. Запись — на каждый запуск, поэтому изменения раздела применяются со следующего запуска
  агента без bootstrap.
- `dispatcher._Runner.run_agent`: перед вызовом — `cfg = await mcp_servers.build_agent_config(session, ctx.vault,
  memory=ctx.config.sandbox.memory, fmt=format_for(workspace.agent))`; `self.secrets += значения cfg.envs`;
  `run_agent(..., mcp_config=cfg.content, extra_envs={k: v.get_secret_value() for k, v in cfg.envs.items()})`.
  `VaultError` пробрасывается — `_run_reserved` уже переводит его в `error` с причиной `vault`.
- `run.sh` и флаги не меняются: `--strict-mcp-config` загружает только сгенерированный файл, `.mcp.json` и hooks
  репозитория не читаются. `claude mcp add` и `~/.claude.json` не используются.
- Плейсхолдер без переменной Claude Code считает ошибкой конфига, поэтому сервис кладёт в `envs` все переменные,
  на которые ссылается `content` (проверка в тесте).

### 6. CLI `harness-server mcp`

Новая группа `mcp_app = typer.Typer(help="Раздел MCP-серверов агента.", no_args_is_help=True)`, `app.add_typer(mcp_app,
name="mcp")`:

- `mcp add NAME --transport http|sse|stdio [--url U] [--command C] [--arg A]... [--env K=V]... [--header "K: V"]...
  [--description D] [--replace]` — разбор `K=V` по первому `=`, заголовка по первому `:` с обрезкой пробелов; ошибки
  валидации → код 1, текст с именем поля, без значения.
- `mcp list` — таблица `name  transport  url|command  description`.
- `mcp show NAME` — все поля; значения `env`/`headers` выводятся как хранятся (ссылки, не секреты).
- `mcp remove NAME`.
CLI не ходит в vault.

## Data flow

CLI → `services/mcp_servers` → `mcp_servers` (ссылки). Запуск агента: `_Runner.run_agent` → `build_agent_config`
(vault → значения) → `run_agent`: `~/.harness/mcp.json` с плейсхолдерами + env со значениями → `claude -p
--strict-mcp-config`.

## Security

- Секретов в БД нет: литеральные ключи в авторизационных полях отклоняются; значения только в env процесса агента и
  в памяти worker.
- Значения добавляются в redaction (`runner.secrets`).
- Изоляция D-36 сохранена; имена `agents-flow`, `project-memory` зарезервированы.
- Агент получает vault MCP как обычную строку раздела; защита — подтверждение владельцем каждого запроса агента (D-45).
  Ожидание подтверждения тратит `AGENT_RUN_TIMEOUT_MIN` (ограничение, механизма нет).

## Backward compatibility

Пустой раздел → `mcp.json` с `agents-flow` (и `project-memory` при памяти) — то же, что писал bootstrap. Миграция только
добавляет таблицу; downgrade её удаляет.

## Test strategy

Postgres (testcontainers) + `FakeVault` + `FakeSandbox`: CRUD и ошибки; валидация (каждое правило п. 1–2);
`build_agent_config` (снапшот JSON, плейсхолдеры ↔ `envs` полностью совпадают, одна ссылка в двух местах — один
запрос vault, `project-memory` с памятью и без, `VaultError`); `ClaudeMcpFormat` (снапшот); `run_agent` (файл записан,
значений нет в файлах, env содержит значения); диспетчер (значение из vault в stderr → `[REDACTED]`); CLI; миграция
(`test_migrations.py`: upgrade/downgrade). Live — tasks раздел 5.

## Rollback

`alembic downgrade` на `0004` удаляет таблицу; без кода сервиса `run_agent` вызывается без `mcp_config`, и действует
статический файл bootstrap.

## Files allowed to change

- `db/migrations/versions/<YYYYMMDD>_0005_mcp_servers.py` (новый), `apps/server/src/harness_server/db/models/mcp.py`
  (новый), `db/models/__init__.py`
- `shared/src/harness_shared/mcp.py` (новый)
- `apps/server/src/harness_server/services/mcp_servers.py`, `services/mcp_formats.py` (новые), `services/sandboxes.py`
- `apps/server/src/harness_server/domain/errors.py`
- `apps/server/src/harness_server/worker/dispatcher.py`, `cli.py`
- `apps/server/tests/test_mcp_servers.py`, `test_mcp_formats.py` (новые), `test_sandbox_service.py`,
  `test_dispatcher.py`, `test_cli.py`, `test_migrations.py`, `test_sandbox_profile_live.py`
- `ARCHITECTURE.md`, `docs/decisions.md`, `docs/deployment.md`, `PLAN.md`, этот каталог OpenSpec

## Risks / Trade-offs

- Глобальный раздел: все workspace видят одинаковые MCP-серверы.
- Запрос vault на каждый запуск агента: недоступный vault → задача `error`.
- Номера плейсхолдеров зависят от порядка записей; это не важно, файл пишется заново при каждом запуске.
