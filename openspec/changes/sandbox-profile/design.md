# Design: sandbox-profile

Открытые вопросы владельцу — в начале `proposal.md`. Решения — D-43…D-45, D-47, D-48 в `docs/decisions.md`.

## Context

Что есть после `mvp-06-sandbox-runtime` (design mvp-06, п. 3–7, 16, 18):

- `deploy/sandbox/bootstrap.sh`: аргументы `--claude-version`, `--openspec-version`, пары `<workspace_id>=<clone_url>`;
  ставит pinned `claude` и `openspec` через `npm install -g` (без переустановки той же версии), создаёт
  `~/.harness/{bin,tasks,worktrees}` и `~/work`, пишет `git-askpass.sh` (токен из env `GITLAB_TOKEN`) и статический
  `~/.harness/mcp.json` с `agents-flow`, клонирует или обновляет `~/work/<workspace_id>`.
- `services/sandboxes.bootstrap(provider, sandbox_id, config, *, script, gitlab_token)` пишет скрипт в
  `/tmp/harness-bootstrap.sh` и выполняет с env `GITLAB_TOKEN`, `timeout_s=BOOTSTRAP_TIMEOUT_SEC` (900); CLI
  `harness-server sandbox bootstrap` отказывает на занятой песочнице, печатает вывод после redaction.
- `services/sandboxes.activate(...)`: `connect`, `extend_timeout`, `git fetch origin` в `~/work/<id>`, worktree.
- `services/sandboxes.run_agent(...)`: env запуска — `CLAUDE_CODE_OAUTH_TOKEN`, `AGENTS_FLOW_TOKEN`, `AGENTS_FLOW_URL`.
- `worker/dispatcher.py`: `DispatchContext` (`gitlab_token`, `secrets` для redaction), `_Runner`, `_run_reserved`,
  `build_dispatch_context`.

Факты песочницы Novita (2026-10-19): Ubuntu 24.04.4, KVM VM, пользователь `user` (uid 1001, группа `sudo`),
`sudo -n true` работает, 2 vCPU / 2 ГБ RAM / 19 ГБ диска, Docker нет, Node 18.19 / npm 9, `claude` предустановлен.

Факты memory-agent (`project-memory`, CLI `memory`, исходник `embeddings/factory.js`): Node ≥ 22.13, Docker Compose v2
(Qdrant + Typesense, `memory service up` идемпотентен); `memory init [--path <dir>]` создаёт `.memory/`, запускает
сервисы и индексирует, неизменённые файлы повторно не индексирует; `memory sync [--path <dir>]` — инкрементально;
`memory mcp --project <abs path>` — MCP по stdio. Приоритет настроек embeddings: **`process.env` > `.memory/.env` >
`config.json`**; без `EMBEDDING_API_KEY` поиск лексический. По умолчанию — Polza, `openai/text-embedding-3-small`.
Индекс один на корень проекта (коллекция = slug каталога + хеш пути).

## Goals / Non-Goals

**Goals:** одна команда `harness-server sandbox bootstrap` готовит песочницу без участия владельца; ключи берутся из
vault и не пишутся на диск песочницы; у агента есть память проекта; изоляция (D-36) не меняется.

**Non-Goals:** репозиторий профиля и его версии; свой шаблон Novita; установка языков; MCP-серверы агента
(`integrations-mcp-config`); наполнение skills и агентов (`skills-library`); повторный bootstrap при активации.

## Decisions

### 1. Ссылка на секрет и vault (D-45)

- Новый модуль `harness_server/vault_ref.py`: `@dataclass(frozen=True) class VaultRef: project: str; service: str;
  name: str`; `VAULT_REF_RE = re.compile(r"^vault:([^/\s][^/]*)/([^/\s][^/]*)/([^/\s][^/]*)$")`;
  `parse_vault_ref(text: str) -> VaultRef | None` (не ссылка → `None`); `is_vault_ref(text) -> bool`;
  `VaultRef.__str__` → `vault:<project>/<service>/<name>`. Части не содержат `/`, кириллица и пробелы внутри частей
  допускаются.
- `adapters/vault/`:
  - `protocol.py`: `class SecretVault(Protocol): async def get(self, ref: VaultRef) -> SecretStr: ...`.
  - `errors.py`: `VaultError(Exception)` с `reason` из `not_configured`, `unavailable`, `timeout`, `tool_error`,
    `invalid_response`; текст — reason и `service/name`, без значений и URL.
  - `fake.py`: `FakeVault(values: Mapping[VaultRef, str], fail: VaultError | None = None)`, журнал запрошенных ссылок.
  - `mcp_client.py`: `McpSecretVault(url: str, token: SecretStr, *, timeout_s: float = VAULT_TIMEOUT_SEC)`,
    `VAULT_TIMEOUT_SEC: Final = 30`. На каждый `get`: клиент Streamable HTTP официального SDK
    (`mcp.client.streamable_http`) с заголовком `Authorization: Bearer <token>`, `ClientSession.initialize()`,
    `call_tool("get_credential", {"project", "service", "name"})`, общий дедлайн `asyncio.timeout(timeout_s)` →
    `timeout`; сеть и протокол → `unavailable`; `isError` → `tool_error`. Значение — чистая функция
    `parse_credential(result) -> SecretStr`: `structuredContent["secret"]`, иначе первый текстовый блок как JSON-объект с
    ключом `secret`; иначе `invalid_response`. Импорт `mcp` — только в этом файле.
  - `__init__.py` реэкспортирует `SecretVault`, `VaultError`, `FakeVault`, `McpSecretVault`.
- `settings.py`: `vault_mcp_url: str | None` (валидатор: только `https://`), `vault_mcp_token: SecretStr | None`.
  `wiring.build_vault(settings) -> SecretVault | None` — `None`, если URL или токен не задан.
- Доступ сервера к vault — без подтверждения (решение владельца). Кэша нет: запрос на каждую команду, которой ключ нужен.
- `async resolve(vault: SecretVault | None, ref: str | None, *, fallback: SecretStr | None) -> SecretStr | None` в новом
  `services/secrets.py`: `ref is None` → `fallback`; ссылка есть, а `vault is None` → `VaultError("not_configured")`;
  иначе `vault.get(parse_vault_ref(ref))`.

### 2. Настройки `harness.yaml` (`config.py`)

- `GitLabConfig.access_ref: str | None = None` — главный ключ GitLab, только формат `vault:…` (валидатор
  `is_vault_ref`). Без него — ENV `GITLAB_TOKEN` (поведение mvp-06). Репозиторий workspace — как сейчас,
  `workspaces[].gitlab_project`.
- `SandboxConfig.memory: SandboxMemoryConfig | None = None`; `SandboxMemoryConfig(version: str (semver),
  embedding_ref: str | None = None (только vault:…))`, `extra="forbid"`. `memory` не задан — память выключена.
- Имена полей проходят существующую проверку запрещённых сегментов (`access_ref`, `embedding_ref` — разрешены).
- `config/harness.example.yaml` — закомментированные примеры.

### 3. Bootstrap

`bootstrap.sh --claude-version V --openspec-version V [--memory-version V] <id>=<url>...` — один режим, все шаги
идемпотентны:

1. Разбор аргументов как сейчас; `--memory-version` — тот же `SEMVER_RE`.
2. `ensure_node`: `node` есть и версия ≥ 22.13 (проверка
   `node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)'`) —
   пропуск. Иначе нужен `sudo -n true` (нет — выход 1 с текстом «нужен Node ≥ 22.13: поставьте вручную или дайте
   sudo»). Установка из репозитория NodeSource без запуска удалённого скрипта, все команды через `sudo -n`, apt с
   `DEBIAN_FRONTEND=noninteractive`: `apt-get install -y ca-certificates curl gnupg`; `install -m 0755 -d
   /etc/apt/keyrings`; ключ `https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key` → `gpg --dearmor -o
   /etc/apt/keyrings/nodesource.gpg`; источник `deb [signed-by=/etc/apt/keyrings/nodesource.gpg]
   https://deb.nodesource.com/node_22.x nodistro main` в `/etc/apt/sources.list.d/nodesource.list`; если стоит пакет
   `npm` из Ubuntu (`dpkg -s npm`) — `apt-get remove -y npm`; `apt-get update && apt-get install -y nodejs`.
3. `npm_global` — обёртка: каталог `$(npm config get prefix)/lib/node_modules` доступен на запись (или его нет, а
   `…/lib` доступен) — `npm "$@"`, иначе `sudo -n npm "$@"`. `ensure_npm_package` ставит через неё (проверка версии —
   как сейчас). На VPS без sudo (mvp-06b) пакеты остаются в пользовательском префиксе.
4. `claude`, `openspec` — как сейчас.
5. Каталоги, `git-askpass.sh`, статический `mcp.json` — как сейчас; плюс `mkdir -p ~/.claude/skills ~/.claude/agents`
   и `chmod 700` обоих (существующие файлы не трогаются).
6. Клоны workspace — как сейчас.
7. Если задан `--memory-version`:
   - `ensure_docker`: `docker compose version` работает — пропуск. Иначе через `sudo -n` (без sudo — выход 1):
     `apt-get install -y ca-certificates curl acl`; ключ `https://download.docker.com/linux/ubuntu/gpg` →
     `/etc/apt/keyrings/docker.asc` (`chmod a+r`); источник `deb [arch=$(dpkg --print-architecture)
     signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo
     "$VERSION_CODENAME") stable` в `/etc/apt/sources.list.d/docker.list`; `apt-get update`; `apt-get install -y
     docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`.
   - Пишет `~/.harness/bin/ensure-docker.sh` (0700, квотированный heredoc): `docker info` успешен — выход 0; иначе
     нужен `sudo -n true`; есть `/run/systemd/system` — `sudo -n systemctl start docker`, иначе
     `sudo -n sh -c 'nohup dockerd >/var/log/dockerd.log 2>&1 &'`; ждать `/var/run/docker.sock` до 30 с;
     `sudo -n setfacl -m "u:$(id -un):rw" /var/run/docker.sock` (доступ без перелогина в группу `docker`);
     `docker info >/dev/null`. Запускает его.
   - `ensure_npm_package project-memory <version>`; `memory service up`.
   - Для каждого workspace: строка `.memory/` добавляется в `~/work/<id>/.git/info/exclude`, если её нет;
     `memory init --path ~/work/<id>`; после успеха `mkdir -p ~/.harness/memory && touch ~/.harness/memory/<id>.ready`.
     `EMBEDDING_API_KEY` приходит только в env команды bootstrap; в `global.env` и `.memory/.env` скрипт его не пишет.

`services/sandboxes.bootstrap(...)` — новые kw-параметры `memory_version: str | None = None`,
`embedding_key: SecretStr | None = None`; при `memory_version` добавить `--memory-version V` перед парами; env
команды: `GITLAB_TOKEN`, `GIT_TERMINAL_PROMPT=0` и `EMBEDDING_API_KEY`, если ключ есть. Таймаут —
`BOOTSTRAP_MEMORY_TIMEOUT_SEC: Final = 1800`, если память включена (первый `memory init` индексирует проекты), иначе
прежний.

### 4. Память проекта (D-47)

- Индекс один на workspace — по клону `~/work/<id>`. Worktree не индексируется: новый корень = новая коллекция и полная
  оплата embeddings на каждую задачу.
- `activate(...)` — новые kw-параметры `default_branch: str = "main"`, `memory_envs: Mapping[str, str] | None = None`.
  После `git fetch` и до проверки worktree одной командой:
  `if [ -f ~/.harness/memory/<id>.ready ] && command -v memory >/dev/null; then bash ~/.harness/bin/ensure-docker.sh &&
  git -C <repo> checkout --quiet --detach --force origin/<default_branch> && memory service up &&
  memory sync --path <repo>; fi` (пути через `shlex.quote`), env — `memory_envs`, `timeout_s=GIT_TIMEOUT_SEC`.
  Ненулевой код → `logger.warning("memory sync failed task=%s exit_code=%s")`, задача продолжается; вывод не
  логируется. Платится только embedding изменённых файлов.
- `run_agent(...)` — новый kw-параметр `extra_envs: Mapping[str, str] | None = None`; env запуска =
  `{**extra_envs, "HARNESS_MEMORY_PROJECT": f"{home}/work/{task.workspace_id}", <три встроенных>}` (встроенные
  перекрывают). MCP-сервер `project-memory` с этой переменной добавляет `integrations-mcp-config`.
- Индекс отражает `origin/<default_branch>`, а не изменения агента. Агент может испортить индекс клона — следующий
  `memory sync` переиндексирует изменённые файлы (принятый риск).
- Ключ embeddings — только env: `memory init` (bootstrap), `memory sync` (активация), позже MCP агента.
- RAM: 2 ГБ, требование заранее не повышается; live 5.3. Провал → открытый вопрос 3.

### 5. Skills и агенты (D-48)

Bootstrap создаёт пустые `~/.claude/skills` и `~/.claude/agents` (user-level). Наполнение — `skills-library` (D-49).
Видимость тестового skill и агента при `--setting-sources user` проверяется live 5.6.

### 6. Рантайм и CLI

- `sandboxes._home` → публичная `home_dir(provider, provider_id) -> str`, все вызовы обновить.
- `dispatcher.DispatchContext` — поле `vault: SecretVault | None = None` (`build_dispatch_context` →
  `build_vault(settings)`). `build_dispatch_context` больше не требует `GITLAB_TOKEN`, если задан
  `config.gitlab.access_ref` (в списке `missing` проверка `GITLAB_TOKEN` — только без `access_ref`);
  `DispatchContext.gitlab_token` становится `SecretStr | None`.
- `_run_reserved` до `activate`: `gitlab = await secrets.resolve(ctx.vault, config.gitlab.access_ref,
  fallback=ctx.gitlab_token)` (`None` → `SandboxStepError("gitlab_token")`); `embedding = await
  secrets.resolve(ctx.vault, config.sandbox.memory.embedding_ref if memory else None, fallback=None)`; значения
  добавляются в `runner.secrets`; `activate(..., gitlab_token=gitlab, default_branch=workspace_for(...).default_branch,
  memory_envs={"EMBEDDING_API_KEY": …} если embedding)`. `VaultError` → `_record_failure(ctx, task.id, "vault", None)`,
  затем обычный `cleanup`.
- `_Runner.run_agent` передаёт `extra_envs={}` (место для `integrations-mcp-config`).
- `cli.sandbox_bootstrap`: `assert_not_busy`; GitLab-ключ и ключ embeddings через `secrets.resolve`
  (`build_vault(settings)`); нет ключа GitLab → «Ошибка конфигурации: нужен gitlab.access_ref или GITLAB_TOKEN», код 1;
  `VaultError` → «Ошибка vault: <reason>», код 1, строка песочницы не меняется; `bootstrap(..., memory_version=…,
  embedding_key=…)`; redaction вывода — `secret_values(settings)` + значения из vault.

## Data flow

Bootstrap (CLI, один раз): `harness.yaml` → ключи из vault (GitLab, embeddings) → `bootstrap.sh` с env (Node, npm,
claude/openspec, каталоги, клоны, Docker, memory-agent, `memory init`).

Задача (worker): `reserve` → ключи из vault → `activate` (`git fetch` с ключом GitLab, `memory sync` с ключом embeddings,
worktree) → `run_agent` (env + `HARNESS_MEMORY_PROJECT`) → `wait_agent` (redaction со всеми значениями) → `cleanup`.

## Security

- Секреты на диск песочницы не пишутся: только env команд. Ключ embeddings — тоже env (приоритет `process.env` в
  memory-agent подтверждён исходником).
- Ключ GitLab агенту не передаётся (только git-команды и bootstrap, как в mvp-06).
- Ссылки на vault лежат в `harness.yaml` (позже в БД) — это не секреты; значения только в памяти процесса.
- Redaction: значения из vault добавляются ко всем текстам из песочницы.
- apt-репозитории NodeSource и Docker — с ключом подписи, удалённые установочные скрипты не исполняются.
- Hooks в профиль пользователя не кладутся; `run.sh` не меняется.

## Backward compatibility

Без `gitlab.access_ref` и `sandbox.memory` поведение mvp-06 сохраняется: ключ из ENV, память пропускается (нет
маркера), bootstrap без `--memory-version`. `ensure_node` на Node ≥ 22.13 ничего не делает; Node 18 без sudo → понятная
ошибка.

## Test strategy

Юнит с `FakeSandbox` и `FakeVault`: `parse_vault_ref`, `parse_credential`, маппинг ошибок `McpSecretVault` (транспорт —
live), `secrets.resolve`, конфиг, `bootstrap` (аргументы, env, таймаут, значений нет в записанном скрипте), `activate`
(шаг памяти: команда с env; сбой не бросает), `run_agent` (`HARNESS_MEMORY_PROJECT` и `extra_envs` в env, не в файлах),
диспетчер (vault-ошибка → `error` и cleanup; значения в `runner.secrets`), CLI. Bash — `shellcheck`. Live — раздел 5 tasks.

## Rollback

Аддитивно, без миграций: убрать `gitlab.access_ref` и `sandbox.memory` из `harness.yaml`. В песочнице —
`memory service down`.

## Files allowed to change

- `deploy/sandbox/bootstrap.sh`
- `apps/server/pyproject.toml`, `uv.lock`
- `apps/server/src/harness_server/vault_ref.py` (новый), `config.py`, `settings.py`, `wiring.py`, `cli.py`
- `apps/server/src/harness_server/adapters/vault/{__init__,protocol,errors,fake,mcp_client}.py` (новые)
- `apps/server/src/harness_server/services/secrets.py` (новый), `services/sandboxes.py`
- `apps/server/src/harness_server/worker/dispatcher.py`
- `apps/server/tests/test_vault.py`, `test_sandbox_profile_live.py` (новые), `test_sandbox_bootstrap.py`,
  `test_sandbox_service.py`, `test_dispatcher.py`, `test_cli.py`, `test_config.py`, `test_settings.py`
- `config/harness.example.yaml`, `.env.example`
- `ARCHITECTURE.md`, `docs/decisions.md`, `docs/deployment.md`, `docs/open-questions.md`, `PLAN.md`, этот каталог OpenSpec

## Risks / Trade-offs

- **Ключи у процессов песочницы.** Ключ embeddings доступен процессам на время команды (позже — агенту, как OAuth-токен,
  D-18). Рекомендация: отдельный ключ Polza для песочницы с лимитом расходов.
- **Vault недоступен** → задача `error` с причиной `vault`.
- **Индекс по базе, а не по worktree.**
- **2 ГБ RAM** — live 5.3.
- **Docker после паузы Novita** — `ensure-docker.sh` при активации.
