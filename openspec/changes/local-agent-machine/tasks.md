# Tasks

> **Контрольная точка (2026-10-26):** отмеченные `[x]` пункты 3.1–3.3, 4.1–4.4,
> 4.6 и 5.1–5.4 означают реализацию, а не приёмку групп 3–5. Astra отклонила
> группы 3–5: 4.5 остаётся `[ ]`, поскольку после двух ограниченных циклов ремонта
> нет принятого теста успешного повторного `init_project`. Это не меняет статусы
> остальных пунктов и не переносится в задачи 6–7.

## 1. Решение и общий протокол (до удаления Novita)

- [ ] 1.1 Записать D-NN в `docs/decisions.md`: отказ от Novita и bootstrap, локальная машина, `agent init`, очищенное окружение подпроцессов, worker на хосте, закрытие `mvp-06b-vps-provider`/`sandbox-timeout-extend`/`cli-version-pin` — файлы: `docs/decisions.md` — проверка: ревью записи, ссылки на заменяемые D-35…D-38, D-40, D-47, D-51, D-62, D-63
- [x] 1.2 Перенести `protocol.py`, `errors.py`, `fake.py` из `adapters/novita` в `adapters/sandbox`, удалить `extend_timeout` из Protocol и `FakeSandbox`, перевести импорты в `services`, `worker`, `cli`, `wiring`, тестах — файлы: `apps/server/src/harness_server/adapters/sandbox/`, перечисленные модули — проверка: `test_sandbox_fake.py` (бывший `test_novita_fake.py`), mypy зелёный

## 2. LocalSandboxProvider

- [x] 2.1 `adapters/local/provider.py`: `connect` (id == `provider_id`, `true`, `$HOME`), `pause` (пусто), `exec` с `start_new_session`, лимитом вывода и таймаутом с `killpg` — файлы: `apps/server/src/harness_server/adapters/local/` — проверка: `test_local_provider.py` (код, stdout, cwd, таймаут убивает группу, чужой id)
- [x] 2.2 Очищенное окружение: белый список `PATH`/`HOME`/`USER`/`LOGNAME`/`LANG`/`LC_*`/`TERM` плюс `envs`, проверка имён и NUL в значениях — файлы: `adapters/local/provider.py` — проверка: тест «секреты worker не видны»: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN` отсутствуют, `AGENTS_FLOW_TOKEN` есть; значение секрета не в argv
- [x] 2.3 `write_file`/`read_file`: права 0600 файлов и 0700 каталогов, атомарная запись, нет файла → `None` — файлы: `adapters/local/provider.py` — проверка: тесты прав и отсутствия файла
- [x] 2.4 Отказ работать от root (uid 0) в `connect` и общий хелпер для `agent init` — файлы: `adapters/local/provider.py`, `services/machine.py` — проверка: тест с подменой uid
- [ ] 2.5 Документация: ARCHITECTURE.md §7 «Песочница» (локальная машина вместо Novita), раздел адаптеров, `apps/server/README.md` — файлы: `ARCHITECTURE.md`, `apps/server/README.md` — проверка: ревью диффа

## 3. Конфиг и ENV

- [x] 3.1 `SandboxConfig`: удалить `claude_code_version`, `openspec_version`; `SandboxMemoryConfig`: удалить `repo`, `ref`, оставить `embedding_ref`; валидатор `before` с сообщением на каждое удалённое поле — файлы: `apps/server/src/harness_server/config.py` — проверка: `test_config.py` (4 поля отклоняются с именем, `memory: {}` валиден)
- [x] 3.2 `Settings`: удалить `novita_api_key`, `novita_domain`; ENV Novita не читаются и не мешают старту — файлы: `settings.py` — проверка: `test_settings.py`
- [x] 3.3 `AgentSettings` для `agent init` (`HARNESS_CONFIG`, `VAULT_MCP_URL`, `VAULT_MCP_TOKEN`, `HARNESS_PUBLIC_URL`) без `DATABASE_URL` и Telegram — файлы: `settings.py` (или `agent_settings.py`) — проверка: тест загрузки без БД и Telegram
- [ ] 3.4 `.env.example`, `config/harness.example.yaml` (`provider_id: local`, без версий и `ref`), `docs/deployment.md` (раздел перехода), таблица ENV в ARCHITECTURE.md §9 — файлы: перечисленные — проверка: grep по `NOVITA` пуст, ревью

## 4. services/machine и команда agent

- [x] 4.1 `services/machine.check_prerequisites`: `git`, `node` ≥ 22.13, `npm`, клиент агента (`AGENT_CLIENT_COMMAND`), `openspec`, при памяти `memory` и `docker compose version`; один отчёт, код 3, без `sudo` — файлы: `apps/server/src/harness_server/services/machine.py` — проверка: `test_machine_service.py` (нет node, несколько программ, Docker при памяти, `sudo` не вызван)
- [x] 4.2 Раскладка `~/.harness/{bin,tasks,worktrees,projects,memory}` и `~/work`, права 0700; запись `mcp.json` с плейсхолдерами 0600 — файлы: `services/machine.py` — проверка: тест содержимого и прав, без значений секретов
- [x] 4.3 Перенос клона/fetch из `services/sandboxes._sync_clone` в `services/machine.sync_clone` (ключ только в env, анонимный клон с предупреждением, каталог не репозиторий → код 1, возврат `origin`) — файлы: `services/machine.py`, `services/sandboxes.py` — проверка: тесты клона, повтора, `origin` возвращён, ключ не в argv и файлах
- [x] 4.4 Память: `.memory/` в `.git/info/exclude`, `memory init` с `EMBEDDING_API_KEY` в env команды, маркер `memory/<id>.ready`; без блока `sandbox.memory` шаг пропускается — файлы: `services/machine.py` — проверка: тесты вкл/выкл, ключ не на диске
- [ ] 4.5 `services/machine.init_project`: порядок шагов, vault (ошибка → код 1 `vault` до изменений), маркер `projects/<id>.ready` ставится в конце и снимается в начале повторного запуска, вывод через redaction — файлы: `services/machine.py` — проверка: тесты полного прохода, сбоя посреди, повтора
- [x] 4.6 `agent_cli.py` (typer, `init <project>`, коды 0/1/2/3, справка с именем харнесса) и `[project.scripts]` `agent`, `harness-agent` — файлы: `apps/server/src/harness_server/agent_cli.py`, `apps/server/pyproject.toml` — проверка: `test_agent_cli.py` (неизвестный проект → 2, без `DATABASE_URL`, справка)
- [ ] 4.7 Документация: ARCHITECTURE.md (слои: `services/machine.py`, `agent_cli.py`), `apps/server/README.md` (`agent init`), `docs/development.md`, `docs/operating-without-ui.md`, `docs/glossary.md` («машина агента», «проект», маркер) — файлы: перечисленные — проверка: ревью

## 5. Рантайм: удаление Novita и bootstrap

- [x] 5.1 `wiring.build_sandbox_provider` → `LocalSandboxProvider` (всегда доступен); `worker._build_dispatch` без условия «ключ Novita»; `cli._provider_or_exit` удалить — файлы: `wiring.py`, `worker/__init__.py`, `cli.py` — проверка: `test_worker.py`, `test_cli.py`
- [x] 5.2 `services/sandboxes.py`: удалить `bootstrap`, `_sync_clone`, константы bootstrap, `_merge_results`, `_remove_bootstrap_script`; убрать `extend_timeout` из `activate`; `_sync_memory` без `ensure-docker.sh`; docstring-и без Novita — файлы: `services/sandboxes.py` — проверка: `test_sandbox_service.py` (activate без `extend_timeout`, `_sync_memory`, release/pause/resume логические)
- [x] 5.3 `cli.py`: удалить `sandbox bootstrap`, `DEFAULT_BOOTSTRAP_SCRIPT`, `_resolve_repo_keys` (если не нужен), справку `sandbox_app` без bootstrap — файлы: `cli.py` — проверка: `test_cli.py` (команда не найдена, код 2)
- [x] 5.4 `worker/dispatcher.py`: проверка маркера `projects/<id>.ready` перед `activate`, причина `project_not_initialized: выполните agent init <id>`, освобождение стандартным путём — файлы: `worker/dispatcher.py` — проверка: `test_dispatcher.py` (нет маркера, есть маркер, песочница освобождена)
- [ ] 5.5 Удалить `adapters/novita/`, `docs/novita.md`, `tools/spikes/novita_check.py`, `deploy/sandbox/`, зависимость `novita-sandbox` из `apps/server/pyproject.toml` и `pyproject.toml`, `uv lock` — файлы: перечисленные, `uv.lock` — проверка: `grep -ri novita apps shared deploy docker-compose.yml .env.example config` пуст, `uv sync --frozen`
- [ ] 5.6 Удалить тесты `test_novita_client.py`, `test_novita_live.py`, `test_sandbox_bootstrap.py`; `conftest.py` и остальные тесты без `NOVITA_*`; live-тесты `test_agent_runtime_live.py`, `test_sandbox_profile_live.py` перевести на локальную машину и `agent init` — файлы: `apps/server/tests/` — проверка: `./tools/harness check`; live — прогон владельцем `-m live`
- [ ] 5.7 Документация: ARCHITECTURE.md (§1 компоненты без bootstrap, §3 `sandboxes`, §7 песочница, §10), `docs/deployment.md` (раздел «Подготовка машины», «Изоляция» вместо Novita), `docs/open-questions.md`, `docs/README.md` — файлы: перечисленные — проверка: ревью

## 6. Деплой: worker на хосте

- [x] 6.1 `docker-compose.yml`: убрать сервис `worker`, ENV `NOVITA_*`; `Dockerfile`: убрать `COPY deploy/sandbox`, обновить комментарий об одном образе — файлы: `docker-compose.yml`, `Dockerfile`, `.dockerignore` — проверка: `docker compose config`, сборка образа
- [x] 6.2 `deploy/worker/agents-flow-worker.service` (systemd user unit, `EnvironmentFile`, `Restart=on-failure`) и `deploy/worker/README.md` — файлы: `deploy/worker/` — проверка: `systemd-analyze --user verify`, ревью
- [x] 6.3 `deploy/db/docker-compose.yml`: публикация Postgres на `127.0.0.1:5432` и описание в `docs/deployment.md` — файлы: `deploy/db/docker-compose.yml`, `docs/deployment.md` — проверка: `docker compose config`, ревью (порт не на внешнем интерфейсе)
- [x] 6.4 CI: убрать шаги и переменные, связанные с Novita и bootstrap — файлы: `.gitlab-ci.yml` — проверка: ревью, `grep -i novita .gitlab-ci.yml` пуст

## 7. Согласование OpenSpec-изменений и переход

- [x] 7.1 Пометки «заменено на local-agent-machine» в `proposal.md`: `mvp-06b-vps-provider`, `sandbox-timeout-extend`, `cli-version-pin` (закрыть без реализации); `opencode-only-client` (отменены задачи 1.3 про каталог-источник конфигурации, 2.1–2.4 про bootstrap и версию OpenCode, 3.1 поле версии; клиентская часть остаётся); `sandbox-pool` (создание песочниц без Novita); `integrations-mcp-config` (генерация `mcp.json` на машине); архив не редактировать — файлы: `openspec/changes/<id>/proposal.md` — проверка: `openspec validate --all`
- [x] 7.2 `PLAN.md`: статус этого изменения, закрытые изменения, обновлённое «Текущее состояние», порядок до `mvp-07`; `CLAUDE.md` §2 и §7 и `AGENTS.md` (стек без Novita, команда `agent init`) — файлы: `PLAN.md`, `CLAUDE.md`, `AGENTS.md` — проверка: ревью
- [ ] 7.3 Руководство перехода подготовлено в `docs/deployment.md`; ручное выполнение и прогон владельцем остаются обязательными — проверка: ревью, прогон владельцем на своей машине

## 8. Проверки

- [ ] 8.1 Прогнать `./tools/harness check` (ruff, ruff format --check, mypy --strict, pytest) и `openspec validate --all` — проверка: зелёный вывод приложен к MR. Локальные зелёные логи есть, но фактическое приложение к MR не выполнено.
- [ ] 8.2 Живая приёмка владельцем на машине: `agent init <project>` дважды, задача от `backlog` до `ready`, `memory status`, поиск значений ключей в `~` пуст — проверка: отчёт владельца в MR

## 9. Память проекта

- [ ] 9.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов — проверка: `memory_status`
