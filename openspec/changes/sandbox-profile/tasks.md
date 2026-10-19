# Tasks

Решения — `design.md` (пункты 1–6) и `docs/decisions.md` D-43…D-45, D-47, D-48. Открытые вопросы — в `proposal.md`;
код делается без ответов, live-раздел 5 ждёт ответов 1–2. Пути — от `apps/server/src/harness_server/`, тесты —
`apps/server/tests/`. Менять только файлы из design «Files allowed to change».

Проверки перед сдачей: `./tools/harness check` (ruff check, ruff format --check, mypy strict, shellcheck
`deploy/sandbox/*.sh`, pytest), `openspec validate sandbox-profile --strict`, `openspec validate --all`.

## 1. Vault и настройки

- [ ] 1.1 `vault_ref.py` (design 1) — проверка: `test_vault.py`: валидные ссылки (в том числе кириллица и пробел в
  части), без префикса, с 2 или 4 частями, с пустой частью → `None`; `str(VaultRef)` обратим
- [ ] 1.2 `mcp==<последняя версия на PyPI в момент реализации, точная>` в `apps/server/pyproject.toml`, `uv lock`;
  версию дописать в D-45 («mcp==X.Y.Z», её же берёт `mvp-07`) — проверка: `uv sync`, mypy
- [ ] 1.3 `adapters/vault/{__init__,protocol,errors,fake,mcp_client}.py`, `wiring.build_vault`, `settings.py`
  (`vault_mcp_url` только https, `vault_mcp_token`), `.env.example` — проверка: `test_vault.py` (`parse_credential`:
  structuredContent, JSON в тексте, нет поля → `invalid_response`; `isError` → `tool_error`; таймаут через подмену
  сессии → `timeout`; текст ошибок без значения и URL; `build_vault` без URL или токена → `None`), `test_settings.py`
- [ ] 1.4 `services/secrets.resolve` — проверка: нет ссылки → fallback; ссылка без vault → `not_configured`; ссылка →
  значение из `FakeVault`
- [ ] 1.5 `config.py`: `GitLabConfig.access_ref`, `SandboxMemoryConfig`, `SandboxConfig.memory`;
  `config/harness.example.yaml` — проверка: `test_config.py` (ссылка не `vault:` → ошибка; версия не semver → ошибка;
  без полей — как раньше)

## 2. Bootstrap и рантайм

- [ ] 2.1 `deploy/sandbox/bootstrap.sh` (design 3: `ensure_node`, `npm_global`, каталоги `~/.claude/{skills,agents}`,
  `--memory-version`, `ensure_docker`, `ensure-docker.sh`, `memory init`, маркеры), шапка и `usage` — проверка:
  `shellcheck`; `test_sandbox_bootstrap.py`: прежние аргументы принимаются; `--memory-version 1.2` → код 2;
  `--help` → код 0; в тексте скрипта нет `EMBEDDING_API_KEY=` с литеральным значением
- [ ] 2.2 `services/sandboxes.py`: `home_dir`, `bootstrap(memory_version, embedding_key)` и таймаут, шаг памяти в
  `activate`, `extra_envs` и `HARNESS_MEMORY_PROJECT` в `run_agent` (design 3, 4) — проверка: `test_sandbox_service.py`:
  `--memory-version` в команде и `EMBEDDING_API_KEY` только в env; активация — команда памяти с `memory_envs`, ненулевой
  код не бросает; `run_agent` — переменные в env запуска, значений нет в `run.sh`, `run.json`, `prompt.md`; прежние
  тесты зелёные без правок ожиданий
- [ ] 2.3 `worker/dispatcher.py` (design 6) — проверка: `test_dispatcher.py`: ключ GitLab из vault по `access_ref`;
  ключ из vault в stderr агента → `[REDACTED]`; `VaultError` → задача `error` с причиной `vault` и cleanup; без ссылок —
  поведение прежнее; без `GITLAB_TOKEN`, но с `access_ref` контекст строится
- [ ] 2.4 `cli.py` `sandbox bootstrap` (design 6) — проверка: `test_cli.py`: ключи из `FakeVault` уходят в env, значение в
  stderr → `[REDACTED]`, `VaultError` → код 1 и строка песочницы не в `error`, нет ни ссылки, ни ENV → код 1

## 3. Документация

- [ ] 3.1 ARCHITECTURE.md §7 (bootstrap, память, ключи из vault) и §9 (ENV `VAULT_MCP_URL`, `VAULT_MCP_TOKEN`, поля
  `gitlab.access_ref`, `sandbox.memory`); `docs/deployment.md` — ссылки vault, первый bootstrap; `docs/open-questions.md`
  — вопрос 4 (клон при bootstrap) и 6 (шаблон не делаем, D-44); PLAN.md — статус — проверка: ревью диффа

## 4. Память проекта харнесса

- [ ] 4.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов

## 5. Live-проверки (владелец, песочница Novita, после ответов на вопросы 1–2)

Новый файл `test_sandbox_profile_live.py` (`-m live`, пропуск без `LIVE_NOVITA_API_KEY`, `LIVE_NOVITA_SANDBOX_ID`,
`LIVE_CLAUDE_CODE_OAUTH_TOKEN`; значения не печатаются). Перед проверками — `harness-server sandbox bootstrap` с
`sandbox.memory` и ссылками на vault.

- [ ] 5.1 Двойной bootstrap: второй запуск — код 0, Node, Docker, npm-пакеты не переустанавливаются («уже установлен»)
- [ ] 5.2 `memory status --json --path ~/work/<id>` с `EMBEDDING_API_KEY` в env команды — Qdrant, Typesense и embeddings
  `ok`; `grep -rlF` значения ключа (через env) в `~`, `~/.config/project-memory`, `~/work` — пусто
- [ ] 5.3 Ресурсы: сервисы memory-agent запущены, агент выполняет `MULTI_TURN_PROMPT` из `test_novita_live.py` — без
  OOM (`dmesg | grep -i oom` пусто), `free -m` в отчёт. Провал → открытый вопрос 3
- [ ] 5.4 Изоляция не изменилась: `test_novita_live.py::test_live_worktree_hooks_and_repo_mcp_are_not_loaded` проходит
- [ ] 5.5 Docker после паузы: `sandbox pause`, `sandbox resume`, `bash ~/.harness/bin/ensure-docker.sh`, `memory status` — `ok`
- [ ] 5.6 Skill и агент видны: тест кладёт `~/.claude/skills/harness-probe/SKILL.md` и
  `~/.claude/agents/harness-probe-agent.md` (frontmatter `name`, `description`), запускает агента с
  `--setting-sources user`; `harness-probe` есть в `system/init` (`skills` или `slash_commands`), `harness-probe-agent` —
  в `system/init.agents`; тест удаляет оба файла
- [ ] 5.7 Активация с памятью: задача-заглушка через диспетчер — `memory sync` без предупреждения в логе, агент запущен
  с `HARNESS_MEMORY_PROJECT`
