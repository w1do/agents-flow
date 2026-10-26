# Design: local-agent-machine

## Context

Сейчас рантайм песочницы устроен так (проверено чтением кода 2026-10-24):

- `adapters/novita` содержит Protocol `SandboxProvider` (`connect`, `exec`, `write_file`, `read_file`, `pause`,
  `extend_timeout`), ошибки, `FakeSandbox` и `NovitaSandboxProvider` (единственный импорт `novita_sandbox`).
  `wiring.build_sandbox_provider` и `worker._build_dispatch` включают диспетчер только при `NOVITA_API_KEY`.
- `services/sandboxes.py`: `bootstrap` (скрипт + клоны + память в три шага, D-62), `activate` (connect,
  `extend_timeout`, fetch, memory sync с `ensure-docker.sh`, worktree), `run_agent`, `wait_agent`, `cleanup_task`,
  `release_sandbox` (pause провайдера), `pause_sandbox`, `resume_sandbox`.
- `cli.py`: `sandbox status|pause|resume|bootstrap`; `Dockerfile` копирует `deploy/sandbox`.
- `deploy/sandbox/bootstrap.sh` ставит Node, `claude`, `openspec`, Docker, `acl`, memory-agent, пишет `mcp.json`.
- Worker сейчас — сервис Compose в Dokploy; команды выполняются в удалённой песочнице.

Решения владельца (2026-10-24, ответы на уточнения): машина локальная (worker на ней же, без SSH); `agent` — собственный
CLI харнесса, ставится на машину один раз вручную; `agent init {project}` делает полное подключение проекта; новое
изменение заменяет пересекающиеся незакрытые (`mvp-06b-vps-provider`, `opencode-only-client`, `sandbox-timeout-extend`,
`cli-version-pin`, часть `sandbox-pool`).

## Goals / Non-Goals

**Goals:** убрать Novita и bootstrap целиком; сохранить весь остальной рантайм (очередь, резервирование
`FOR UPDATE SKIP LOCKED`, worktree на задачу, токены задачи, итог агента, очистка, гейты, память, vault, redaction);
подключение проекта одной идемпотентной командой; секреты worker не попадают в процессы агента.

**Non-Goals:** SSH и несколько машин; изоляция агента VM или контейнером; переименование `sandbox*`; миграции БД;
переход на OpenCode; установка инструментов харнессом.

## Decisions

### 1. Локальный провайдер за тем же Protocol, адаптер Novita удаляется

`adapters/sandbox/{protocol,errors,fake}.py` получают Protocol, ошибки и `FakeSandbox` (переезд из `adapters/novita`),
`adapters/local/provider.py` — `LocalSandboxProvider`. Из Protocol удаляется `extend_timeout` (понятие
Novita, у постоянной машины нет таймаута жизни); `pause` остаётся методом Protocol и в локальной реализации пустой, чтобы
`release_sandbox` и CLI менялись минимально. `adapters/novita` удаляется целиком без реэкспорта.

Отвергнуто: оставить Novita вторым провайдером под флагом (владелец просит полное удаление, лишний код и зависимость
`novita-sandbox`); писать `exec` прямо в сервисе через `subprocess` (нарушает правило «внешнее — только через адаптер»
и ломает тесты на `FakeSandbox`).

### 2. Семантика локального провайдера

- `connect(id)`: `id` должен совпасть с `sandbox.provider_id` (логическое имя машины, `local`), иначе `SandboxNotFound`;
  проверка — запуск `true` и существование `$HOME`; сбой → `SandboxUnavailable("unreachable")`.
- `exec(cmd, envs, cwd, timeout_s)`: `asyncio.create_subprocess_exec("bash", "-lc", cmd)` с `start_new_session=True`,
  stdout/stderr читаются целиком с ограничением размера; ненулевой код → `ExecResult`; таймаут → `killpg` всей
  группы и `SandboxUnavailable("timeout")`. Команды, которые запускают агента (`setsid nohup bash run.sh &`), остаются
  как есть и переживают рестарт worker.
- Окружение подпроцесса собирается с нуля: белый список `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_*`, `TERM`
  плюс `envs` вызова. Остальное из env worker (`DATABASE_URL`, `HARNESS_SECRET_KEY`, `TELEGRAM_*`, `VAULT_MCP_TOKEN`,
  `POLZA_AI_KEY`) не наследуется. Имена `envs` проверяются (`^[A-Z_][A-Z0-9_]*$`), значения с NUL отклоняются.
- `write_file`/`read_file` — прямые операции с файлами: права файлов 0600, каталогов 0700, запись атомарная
  (`tmp` и `rename`); нет файла → `None`. Пути абсолютные: `~` не раскрывается (как сейчас, `home_dir` отдаёт `$HOME`).
- `pause` — пустая операция (DEBUG-запись).

Отвергнуто: наследовать env worker и вычищать секреты чёрным списком (новый секрет в Settings утёк бы по умолчанию);
передавать секреты аргументами (виден в `ps`); `pexpect`/PTY (не нужен, агент работает в фоне).

### 3. `agent` — вторая точка входа пакета `harness-server`, логика в сервисе

В `apps/server/pyproject.toml` добавляется `[project.scripts] agent = "harness_server.agent_cli:app"` и алиас
`harness-agent` (на машине `agent` может конфликтовать с другими CLI с таким именем, например с Cursor CLI; алиас
не зависит от порядка `PATH`). `agent_cli.py` — тонкий вход (typer, подкоманда `init`, затем возможны `status`), вся
логика — `services/machine.py` (`init_project`, `check_prerequisites`, `write_mcp_config`, `sync_clone`,
`init_memory`), которая использует `LocalSandboxProvider` и `adapters/vault`. Клонирование переиспользует
`services/git_access` и логику `_sync_clone`, переносимую из `services/sandboxes.py`.

Отвергнуто: отдельный пакет `apps/agent` с копией кода (дублирование `git_access`, `vault`, `redaction`, второй
`pyproject`); подкоманда `harness-server sandbox init` (владелец явно просит `agent init {project}`); bash-скрипт
(повторяет прежний bootstrap со всеми его экранированиями и тестами).

### 4. Лёгкие настройки для `agent init`

`load_settings()` требует `DATABASE_URL`, Telegram и пр. `agent init` их не использует, поэтому вводится
`AgentSettings` (pydantic-settings, `HARNESS_CONFIG`, `VAULT_MCP_URL`, `VAULT_MCP_TOKEN`, `HARNESS_PUBLIC_URL`
опционально). Значения читаются из ENV процесса оператора; файл `.env` не читается.

Отвергнуто: ослабить обязательные ENV общего `Settings` (риск тихого старта сервера без БД и Telegram, D-20).

### 5. Предпосылки: проверка вместо установки, один отчёт

`check_prerequisites` выполняет `command -v` и `--version` для `git`, `node` (≥ 22.13), `npm`, клиента агента
(константа `AGENT_CLIENT_COMMAND = "claude"`; её заменяет `opencode-only-client`), `openspec`, а при памяти — `memory`
и `docker compose version`. Отчёт собирается целиком, код 3. Никакого `sudo`, `apt`, `npm install -g`, `curl | sh`.
До первых изменений ФС проверка root (uid 0 → код 1).

Отвергнуто: «умная» установка недостающего (возвращает прежний bootstrap и повышение привилегий); проверка только
клиента агента (поздний, непонятный сбой на `openspec` или `memory`).

### 6. Раскладка и маркеры

`~/.harness/{bin,tasks,worktrees,projects,memory}` (права 0700), `~/work/<project>`. Маркеры:
`~/.harness/projects/<project>.ready` ставит только `agent init` после всех шагов (атомарно `tmp` + `rename`), снимает
при начале повторного `agent init` (чтобы сбой не оставлял «готово»); `~/.harness/memory/<project>.ready` как раньше
(по нему `_sync_memory` решает, обновлять ли индекс). `ensure-docker.sh` не создаётся: Docker на постоянной машине
запущен владельцем, `_sync_memory` убирает вызов скрипта.

Отвергнуто: определять готовность по наличию клона (клон может быть оборван, память и `mcp.json` не проверены);
хранить статус проектов в БД (нужна миграция и доступ к БД из `agent init`).

### 7. Проверка маркера в диспетчере

В `worker/dispatcher.py` перед `activate` выполняется `test -f ~/.harness/projects/<id>.ready`; нет файла → задача
`error` с причиной `project_not_initialized: выполните agent init <id>`, песочница освобождается стандартным путём
(cleanup, release). Это единственный новый код пути выполнения.

Отвергнуто: молча делать `agent init` из worker (секреты vault и клон в обработчике задач, длинная операция без
оператора, повторяет bootstrap); падать на `fetch` (непонятная причина `fetch` вместо действия для владельца).

### 8. Конфиг: удаление полей с подсказкой

`SandboxConfig`: убираются `claude_code_version`, `openspec_version`; `SandboxMemoryConfig`: убираются `repo`, `ref`
(остаётся `embedding_ref`; блок `memory: {}` включает память). Валидатор `mode="before"` отвечает на каждое удалённое
поле сообщением с именем и причиной (образец — D-60). `provider_id` остаётся, пример значения — `local`.
`Settings.novita_api_key`/`novita_domain` удаляются без отклонения ENV (лишняя переменная не должна ломать старт).

Отвергнуто: молча игнорировать старые поля (`extra="forbid"` и так ловит, но без подсказки; тихий игнор скрывает, что
версии больше не ставятся); оставлять версии «для информации» (вводит в заблуждение, как закреплённая версия, которая
ничего не закрепляет).

### 9. Где работает worker

Worker исполняет команды локально, значит работает под пользователем машины с агентом. В Dokploy-стеке остаются
`migrate` и `server`; `worker` из `docker-compose.yml` удаляется. Для хоста добавляется
`deploy/worker/agents-flow-worker.service` (systemd user unit, `EnvironmentFile` вне репозитория, `Restart=on-failure`).
Postgres из `deploy/db` публикуется на `127.0.0.1:5432` (только loopback), `DATABASE_URL` worker смотрит туда.
`HARNESS_PUBLIC_URL` по-прежнему внешний HTTPS: агент ходит в MCP по нему.

Отвергнуто: оставить worker в контейнере и монтировать домашний каталог/бинарники хоста (разные uid и libc, агент
запускает Docker для memory, хрупко); `network_mode: host` для контейнера (не решает доступ к инструментам хоста);
DinD (избыточно). Если Dokploy и машина агента — разные хосты, `DATABASE_URL` придётся доставлять приватной
сетью или туннелем: вне этого изменения (см. Open Questions).

### 10. Что не меняется

`services/sandboxes.run_agent`, `wait_agent`, `cleanup_task`, статусы `SandboxStatus`, таблица `sandboxes`, колонки
`agent_started_at`/`agent_pid` (D-41), redaction, токены задачи, `git_access`, `adapters/vault`. Меняются только
`activate` (убирается `extend_timeout`), `_sync_memory` (убирается `ensure-docker.sh`), `release_sandbox`/
`pause_sandbox`/`resume_sandbox` (провайдер вызывается формально, поведение логическое).

## Data flow

Оператор на машине: `agent init demo` → проверка предпосылок → `AgentSettings` → vault (ключ репозитория, ключ
embeddings) → `LocalSandboxProvider` → `mkdir ~/.harness/*` → clone/fetch → `mcp.json` → `memory init` → маркеры.
Worker: резервирование → маркер проекта → `activate` (fetch, worktree) → `run_agent` (env: токен задачи, URL MCP,
OAuth-токен клиента, `GIT_*`) → `wait_agent` → гейты → `cleanup_task` → `release_sandbox`.

## Security

- Агент больше не изолирован облачной VM: он работает с правами пользователя машины и `bypassPermissions`. Обязательная
  рекомендация: отдельный пользователь ОС без sudo, лучше отдельная машина или VM; `agent init` и worker отказываются
  работать от root. Документируется в `docs/deployment.md` (раздел «Изоляция» заменяет раздел про Novita).
- Очищенное окружение подпроцессов закрывает утечку секретов worker (`DATABASE_URL`, токены) в агента. Остаточный риск:
  агент читает `/proc/<pid>/environ` процессов того же пользователя, поэтому worker и агент должны работать под
  разными пользователями, если на машине есть иные секреты (R-1 D-62 сохраняется и расширяется).
- Исходящий allowlist Novita (`network.allow_out`) исчезает; сетевое ограничение — на стороне владельца (firewall).
- Ключи vault и репозиториев: только env команды, вывод `agent init` проходит redaction, `mcp.json` с плейсхолдерами 0600.
- `agent init` не вызывает `sudo` и не пишет вне `$HOME`.

## Backward compatibility

Ломающее: конфиг со старыми полями не загружается; ENV Novita игнорируются; команда `sandbox bootstrap` исчезает;
сервис `worker` уходит из Compose. Порядок перехода: поставить инструменты на машину, обновить `harness.yaml` (удалить
поля, `provider_id: local`), `agent init <project>` для каждого workspace, запустить worker юнитом, затем
перераспределить Compose. Миграций БД нет; строка `sandboxes` со старым `provider_id` Novita не используется:
`ensure_sandbox` создаёт строку для `local`, старую строку владелец удаляет вручную (задача 7.3).

## Test strategy

- `test_local_provider.py`: `exec` (код, stdout, `cwd`, `envs`), очищенное окружение (секреты worker не видны),
  таймаут убивает группу, имена env, файлы 0600/0700, `read_file` нет файла, `connect` с чужим id.
- `test_machine_service.py` (с `FakeSandbox` или локальным провайдером в `tmp_path` как HOME): предпосылки (все
  отсутствующие сразу, версия node), клон/повтор, каталог не репозиторий, ключ только в env, анонимный клон,
  vault недоступен, `mcp.json` с плейсхолдерами и 0600, память вкл/выкл, маркеры, root отклонён.
- `test_agent_cli.py`: `agent init` (коды 0/1/2/3), справка, без `DATABASE_URL`.
- `test_sandbox_service.py`/`test_dispatcher.py`: `project_not_initialized`, `activate` без `extend_timeout`,
  `_sync_memory` без `ensure-docker.sh`, release/pause логические; тесты `bootstrap` удалены.
- `test_config.py`/`test_settings.py`: отклонение удалённых полей с именами, `memory: {}`, отсутствие `novita_*`.
- Удаляются: `test_novita_client.py`, `test_novita_live.py`, `test_sandbox_bootstrap.py`; `test_novita_fake.py`
  переименовывается в `test_sandbox_fake.py`. Live-тесты `test_agent_runtime_live.py`, `test_sandbox_profile_live.py`
  переводятся на локальную машину и `agent init` (`-m live`).
- `grep -ri novita` по `apps/ shared/ deploy/ docker-compose.yml .env.example config/` пуст (кроме ADR и архива);
  `./tools/harness check` зелёный.

## Rollback

Откат — git revert изменения (код, тесты, документация, Compose). Миграций нет; Novita-песочница после отката
пересоздаётся владельцем, bootstrap возвращается из истории git.

## Files allowed to change

- Код: `apps/server/src/harness_server/{adapters/novita,adapters/sandbox,adapters/local,services/sandboxes.py,
  services/machine.py,services/git_access.py (только перенос вспомогательных вызовов),cli.py,agent_cli.py,wiring.py,
  settings.py,config.py,worker/__init__.py,worker/dispatcher.py}`, `apps/server/pyproject.toml`, `pyproject.toml`,
  `uv.lock`.
- Тесты: `apps/server/tests/` (перечень в Test strategy и `conftest.py`).
- Удаляются: `deploy/sandbox/`, `docs/novita.md`, `tools/spikes/novita_check.py`.
- Деплой: `Dockerfile`, `docker-compose.yml`, `deploy/db/docker-compose.yml`, новый `deploy/worker/`, `.dockerignore`.
- Конфиг и документация: `.env.example`, `config/harness.example.yaml`, `config/harness.yaml` (локальный),
  `ARCHITECTURE.md`, `PLAN.md`, `CLAUDE.md`, `AGENTS.md`, `docs/{deployment,development,glossary,decisions,
  operating-without-ui,open-questions,README}.md`, `apps/server/README.md`.
- OpenSpec: этот каталог; пометки в `proposal.md` изменений `mvp-06b-vps-provider`, `sandbox-timeout-extend`,
  `cli-version-pin`, `opencode-only-client`, `sandbox-pool`, `integrations-mcp-config` (только если упоминает bootstrap).

## Risks / Trade-offs

- [Нет изоляции VM: агент с `bypassPermissions` на машине владельца] → отдельный пользователь без sudo/root-отказ,
  рекомендация отдельной машины, firewall владельца; риск принят владельцем явно (ответ 2026-10-24).
- [Имя `agent` конфликтует с другим CLI на `PATH`] → алиас `harness-agent`, документация, `agent --help` называет харнесс.
- [Postgres на loopback хоста и worker на хосте: другая схема деплоя, чем D-59] → привязка только к `127.0.0.1`;
  если хосты разные — Open Question; откат — вернуть сервис в Compose.
- [Дрейф версий инструментов без закрепления (C8)] → `agent init` печатает версии; закрепление — ответственность
  владельца; `cli-version-pin` закрывается.
- [Потеря процессов агента при рестарте worker] → не меняется: агент запускается `setsid nohup`, итог по файлам и БД (D-41).
- [Старая строка `sandboxes` Novita] → не берёт задач (другой `provider_id`), удаляется вручную по задаче 7.3.

## Open Questions

- Работают ли Dokploy и машина агента на одном хосте? Если нет, нужен способ доставить `DATABASE_URL` для worker
  (приватная сеть, туннель). До ответа принято: один хост, Postgres на `127.0.0.1`.
- Нужна ли команда `agent status` (проекты, маркеры, версии инструментов)? В этом изменении не входит; добавляется
  отдельным изменением по запросу.
