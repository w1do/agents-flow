# Tasks

Решения — `design.md` (пункты 1–6), D-45, D-46. Начинать после принятия `sandbox-profile`. Пути — от
`apps/server/src/harness_server/`, тесты — `apps/server/tests/`, миграции — `db/migrations/versions/`. Менять только
файлы из design «Files allowed to change».

Проверки перед сдачей: `./tools/harness check`, `openspec validate integrations-mcp-config --strict`,
`openspec validate --all`.

## 1. Хранение

- [ ] 1.1 `harness_shared/mcp.py` (`McpTransport`, `McpServerInput`, `McpServerView` с валидаторами design 1–2),
  `db/models/mcp.py`, миграция `0005` — проверка: `test_migrations.py` (upgrade/downgrade, CHECK и UNIQUE),
  `test_mcp_servers.py` — валидация: имя `agents-flow`; `http` без `url`; `http://`; `stdio` с `headers`;
  `Authorization` без ссылки; `env` `API_KEY` без ссылки; `Bearer vault:a/b/c` принят; `vault:a/b` отклонён; `${` в `args`
- [ ] 1.2 `services/mcp_servers.py`: `add_server` (с `replace`), `list_servers`, `get_server`, `remove_server`;
  `McpServerExists`, `McpServerNotFound` в `domain/errors.py` — проверка: `test_mcp_servers.py` (Postgres): повтор без
  `replace` → `McpServerExists`, с `replace` — обновление; удаление несуществующего → `McpServerNotFound`

## 2. Конфиг агента

- [ ] 2.1 `services/mcp_formats.py`: `RenderedServer`, `McpConfigFormat`, `ClaudeMcpFormat`, `FORMATS`, `format_for` —
  проверка: `test_mcp_formats.py` (снапшот JSON для http и stdio; неизвестный тип агента → `KeyError`)
- [ ] 2.2 `build_agent_config` (design 3) — проверка: снапшот для vault-сервера (`Bearer vault:…`) и stdio-сервера с env;
  множество плейсхолдеров `${…}` в `content` = ключи `envs` ∪ {`AGENTS_FLOW_URL`, `AGENTS_FLOW_TOKEN`,
  `HARNESS_MEMORY_PROJECT`}; одна ссылка дважды → один запрос `FakeVault`; `project-memory` есть при `memory` и нет без;
  ссылка без vault → `VaultError("not_configured")`
- [ ] 2.3 `sandboxes.run_agent(mcp_config=)` и `dispatcher._Runner.run_agent` (design 5) — проверка:
  `test_sandbox_service.py`: файл `~/.harness/mcp.json` записан до запуска, `chmod 600` выполнен, значений из vault нет в
  файлах, они есть в env запуска; `test_dispatcher.py`: значение из vault в stderr агента → `[REDACTED]`, `VaultError` →
  задача `error` с причиной `vault`

## 3. CLI

- [ ] 3.1 `cli.py` группа `mcp`: `add`, `list`, `show`, `remove` (design 6) — проверка: `test_cli.py` (add → list → show
  → remove; ошибка валидации → код 1 без значения в тексте; `--env K=V=W` → значение `V=W`)

## 4. Документация и память

- [ ] 4.1 ARCHITECTURE.md (§3 таблица `mcp_servers`, §7 генерация `mcp.json`, §9 команда `harness-server mcp`);
  `docs/deployment.md` — как добавить сервер vault и preferences; PLAN.md — статус — проверка: ревью диффа
- [ ] 4.2 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов

## 5. Live-проверки (владелец, после ответов на вопросы и bootstrap из `sandbox-profile`)

- [ ] 5.1 `harness-server mcp add vault --transport http --url <vault MCP> --header "Authorization: Bearer
  vault:<project>/<service>/<name>"`; запуск агента как в `run.sh` с сгенерированным файлом и env — в
  `system/init.mcp_servers` есть `vault`, `project-memory`, `agents-flow` со статусом `connected`
- [ ] 5.2 `grep -rlF` значения ключа vault агента (через env) в `~` и worktree — пусто; `~/.harness/mcp.json` содержит
  `${HARNESS_MCP_…}`, а не значение
- [ ] 5.3 Изоляция: `test_novita_live.py::test_live_worktree_hooks_and_repo_mcp_are_not_loaded` проходит, плюс тест того же
  вида с сгенерированным `~/.harness/mcp.json`: hook-ловушка не срабатывает, `trap` из `.mcp.json` worktree не подключён,
  `vault` подключён
- [ ] 5.4 `harness-server mcp remove vault` → следующий запуск агента без `vault` в `system/init.mcp_servers`
