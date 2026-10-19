# Tasks

Решения — `design.md` (пункты 1–6) и `docs/decisions.md` D-43…D-45, D-47, D-48, D-51. Открытые вопросы — в `proposal.md`;
код делается без ответов, live-раздел 5 ждёт ответов 1–2. Пути — от `apps/server/src/harness_server/`, тесты —
`apps/server/tests/`. Менять только файлы из design «Files allowed to change».

Проверки перед сдачей: `./tools/harness check` (ruff check, ruff format --check, mypy strict, shellcheck
`deploy/sandbox/*.sh`, pytest), `openspec validate sandbox-profile --strict`, `openspec validate --all`.

## 1. Vault и настройки

- [x] 1.1 `vault_ref.py` (design 1) — проверка: `test_vault.py`: валидные ссылки (в том числе кириллица и пробел в
  части), без префикса, с 2 или 4 частями, с пустой частью → `None`; `str(VaultRef)` обратим
- [x] 1.2 `mcp==<последняя версия на PyPI в момент реализации, точная>` в `apps/server/pyproject.toml`, `uv lock`;
  версию дописать в D-45 («mcp==X.Y.Z», её же берёт `mvp-07`) — проверка: `uv sync`, mypy
- [x] 1.3 `adapters/vault/{__init__,protocol,errors,fake,mcp_client}.py`, `wiring.build_vault`, `settings.py`
  (`vault_mcp_url` только https, `vault_mcp_token`), `.env.example` — проверка: `test_vault.py` (`parse_credential`:
  structuredContent, JSON в тексте, нет поля → `invalid_response`; `isError` → `tool_error`; таймаут через подмену
  сессии → `timeout`; текст ошибок без значения и URL; `build_vault` без URL или токена → `None`), `test_settings.py`
- [x] 1.4 `services/secrets.resolve` — проверка: нет ссылки → fallback; ссылка без vault → `not_configured`; ссылка →
  значение из `FakeVault`
- [x] 1.5 `config.py`: `GitLabConfig.access_ref`, `SandboxMemoryConfig`, `SandboxConfig.memory`;
  `config/harness.example.yaml` — проверка: `test_config.py` (ссылка не `vault:` → ошибка; версия не semver → ошибка;
  без полей — как раньше). Поле `version` заменено на `repo`/`ref` по D-51 — задача 2.5

## 2. Bootstrap и рантайм

- [x] 2.1 `deploy/sandbox/bootstrap.sh` (design 3: `ensure_node`, `npm_global`, каталоги `~/.claude/{skills,agents}`,
  `--memory-version`, `ensure_docker`, `ensure-docker.sh`, `memory init`, маркеры), шапка и `usage` — проверка:
  `shellcheck`; `test_sandbox_bootstrap.py`: прежние аргументы принимаются; `--memory-version 1.2` → код 2;
  `--help` → код 0; в тексте скрипта нет `EMBEDDING_API_KEY=` с литеральным значением. `--memory-version` и
  `ensure_npm_package project-memory` заменены по D-51 — задача 2.6
- [x] 2.2 `services/sandboxes.py`: `home_dir`, `bootstrap(memory_version, embedding_key)` и таймаут, шаг памяти в
  `activate`, `extra_envs` и `HARNESS_MEMORY_PROJECT` в `run_agent` (design 3, 4) — проверка: `test_sandbox_service.py`:
  `--memory-version` в команде и `EMBEDDING_API_KEY` только в env; активация — команда памяти с `memory_envs`, ненулевой
  код не бросает; `run_agent` — переменные в env запуска, значений нет в `run.sh`, `run.json`, `prompt.md`; прежние
  тесты зелёные без правок ожиданий. Kw `memory_version` заменён на `memory_ref`/`memory_repo` по D-51 — задача 2.7
- [x] 2.3 `worker/dispatcher.py` (design 6) — проверка: `test_dispatcher.py`: ключ GitLab из vault по `access_ref`;
  ключ из vault в stderr агента → `[REDACTED]`; `VaultError` → задача `error` с причиной `vault` и cleanup; без ссылок —
  поведение прежнее; без `GITLAB_TOKEN`, но с `access_ref` контекст строится
- [x] 2.4 `cli.py` `sandbox bootstrap` (design 6) — проверка: `test_cli.py`: ключи из `FakeVault` уходят в env, значение в
  stderr → `[REDACTED]`, `VaultError` → код 1 и строка песочницы не в `error`, нет ни ссылки, ни ENV → код 1.
  Передача `memory.version` заменена на `memory.ref`/`memory.repo` по D-51 — задача 2.7

Задачи 2.5–2.7 (D-51, решение владельца 2026-10-19): memory-agent ставится из GitHub по полному sha коммита, а не
пакетом `project-memory` из реестра npm (там чужой пакет). В тестах — фиктивный sha
`0123456789abcdef0123456789abcdef01234567` (константа `MEMORY_REF` в каждом тестовом модуле), не настоящий закреплённый
коммит: настоящий живёт только в боевом `harness.yaml`, `docs/deployment.md` и D-51.

- [x] 2.5 `config.py` (design 2): в `SandboxMemoryConfig` удалить `version`; добавить константы модуля
  `_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"`, `_GITHUB_REPO_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"` и поля (в этом
  порядке, перед `embedding_ref`) `repo: str = Field(default="w1do/memory-agent", pattern=_GITHUB_REPO_PATTERN)`,
  `ref: str = Field(pattern=_GIT_SHA_PATTERN)`; комментарии: `repo` — GitHub-репозиторий memory-agent, `ref` — полный
  sha коммита, тег и ветка изменяемы (D-51). `config/harness.example.yaml`: в закомментированном блоке `memory:`
  заменить строки про версию на `#   # GitHub-репозиторий memory-agent (по умолчанию w1do/memory-agent).`,
  `#   # repo: w1do/memory-agent`, `#   # Полный sha коммита memory-agent (40 символов 0-9a-f), не тег (D-51).`,
  `#   ref: CHANGE_ME_40_HEX_COMMIT_SHA` — проверка: `test_config.py`: в тесте с блоком `memory` заменить
  `version: 1.2.3` на `ref: <MEMORY_REF>` и проверять `memory.ref == MEMORY_REF`, `memory.repo == "w1do/memory-agent"`;
  `test_memory_version_must_be_semver` переименовать в `test_memory_ref_must_be_full_commit_sha` и параметризовать
  значениями `v1.0.0`, `main`, `09e5e63` (короткий), sha в верхнем регистре, 41 символ → `ConfigError`, в тексте
  `memory.ref`; новый `test_memory_repo_must_be_owner_slash_name` (`a/b/c`, `w1do`, `w1do/memory agent` →
  `ConfigError` с `memory.repo`; `other-org/memory-agent.fork` принимается); новый `test_memory_version_field_is_rejected`
  (`version: 1.2.3` рядом с `ref` → `ConfigError`, `extra="forbid"`); блок без `ref` → `ConfigError`
- [x] 2.6 `deploy/sandbox/bootstrap.sh` (design 3, п. 1 и 7): шапка (пример `--memory-ref <sha> --memory-repo
  w1do/memory-agent`) и `usage` (строка `[--memory-ref SHA --memory-repo OWNER/NAME]`, пояснение: memory-agent из
  GitHub по полному sha коммита); переменные `memory_ref=""`, `memory_repo=""` вместо `memory_version`; разбор
  `--memory-ref`/`--memory-repo` в той же ветке `case`, что версии; `SHA_RE`, `GH_REPO_RE` и три текста ошибок из
  design 3 п. 1 (код 2); условие блока памяти `if [ -n "$memory_ref" ]; then`; функция `ensure_memory_agent` строго
  по design 3 п. 7 вместо `ensure_npm_package project-memory "$memory_version"`; `mkdir -p "$HARNESS_DIR/memory"`
  остаётся перед циклом по workspace. `ensure_npm_package` и `npm_global` не меняются; снятие ключей из env в начале
  не меняется — проверка: `shellcheck deploy/sandbox/*.sh`; `test_sandbox_bootstrap.py`:
  `test_script_rejects_malformed_memory_version` → `test_script_rejects_malformed_memory_ref` (параметры `v1.0.0`,
  `09e5e63`, `main` при валидном `--memory-repo w1do/memory-agent` → код 2, `--memory-ref` в stderr); новый
  `test_script_rejects_malformed_memory_repo` (`--memory-ref <MEMORY_REF> --memory-repo a/b/c` → код 2, `--memory-repo`
  в stderr); новый `test_script_requires_memory_ref_and_repo_together` (только `--memory-ref <MEMORY_REF>` → код 2;
  только `--memory-repo w1do/memory-agent` → код 2); новый `test_script_rejects_removed_memory_version_flag`
  (`--memory-version 1.2.3` → код 2, `неизвестный аргумент` в stderr); `test_script_help_exits_zero` — в stdout
  `--memory-ref` и `--memory-repo`; `test_script_runs_argument_path_with_secrets_in_env` — `--memory-ref x` вместо
  `--memory-version x` (код 2); новый `test_script_installs_memory_agent_from_github_pinned_commit`: в тексте скрипта
  есть `spec="github:${memory_repo}#${memory_ref}"` и `npm_global install -g "$spec"`, нет `project-memory@` и
  `ensure_npm_package project-memory`; позиция `npm_global install -g "$spec"` меньше позиции
  `mv "$marker.tmp" "$marker"`; `installed-ref` в тексте; прежние тесты про секреты (`unset`, присваивания ключей,
  литерал `EMBEDDING_API_KEY`) зелёные без правок ожиданий. Все вызовы скрипта в тестах — до установок (код 2/0),
  сеть не нужна
- [x] 2.7 `services/sandboxes.py` `bootstrap` (design 3, последний абзац): kw `memory_version` → `memory_ref: str |
  None = None`, `memory_repo: str | None = None`; проверка «оба или ни одного» → `ValueError` до `provider.connect`;
  аргументы `--memory-ref <ref> --memory-repo <repo>` перед парами; таймаут 1800 при `memory_ref`; docstring: memory_ref
  — полный sha коммита memory-agent, memory_repo — его GitHub-репозиторий (D-51). `cli.py` `sandbox_bootstrap`:
  `memory_ref=memory.ref if memory is not None else None`, `memory_repo=memory.repo if memory is not None else None` —
  проверка: `test_sandbox_bootstrap.py`: `test_memory_version_goes_to_script_args_and_key_only_to_env` →
  `test_memory_ref_goes_to_script_args_and_key_only_to_env`, ожидаемая команда
  `bash <BOOTSTRAP_SCRIPT_PATH> --claude-version 2.1.292 --openspec-version 1.14.3 --memory-ref <MEMORY_REF>
  --memory-repo w1do/memory-agent demo=https://gitlab.com/group/demo.git` (одна строка), env-ключи и проверки ключа —
  прежние; `test_memory_bootstrap_uses_longer_timeout` — `memory_ref=MEMORY_REF, memory_repo="w1do/memory-agent"`,
  ожидание `[1800]`; новый `test_bootstrap_rejects_memory_ref_without_repo` (и наоборот) → `ValueError`, в журнале
  `FakeSandbox` нет записей; `test_sandbox_service.py::test_bootstrap_with_memory_keeps_embedding_key_off_disk` —
  `memory_ref=MEMORY_REF, memory_repo="w1do/memory-agent"`; `test_cli.py`: в `_write_vault_config(memory=True)` —
  `"ref": MEMORY_REF` вместо `"version": "1.2.3"`, ожидание `f"--memory-ref {MEMORY_REF} --memory-repo w1do/memory-agent"`
  в командах журнала вместо `--memory-version 1.2.3`; `grep -rn "memory_version\|memory-version\|memory\.version"
  apps/server deploy config` — пусто (кроме имени теста `test_script_rejects_removed_memory_version_flag` и строки
  `--memory-version` в нём, и `test_memory_version_field_is_rejected`); `./tools/harness check` зелёный

- [x] 2.8 Авторизация git через заголовок на префикс URL (D-52, заменяет askpass из ревью S1): `deploy/sandbox/bootstrap.sh`
  — аргумент `--gitlab-url <https://host[/path]>` (валидация: только https, без учётных данных, пробелов и query; код 2;
  завершающий слэш нормализуется), без `--gitlab-url` при клонах — код 2; без токена — анонимный git без заголовка (публичные репозитории);
  заголовок `Authorization: Basic` собирается встроенными средствами из неэкспортируемой `$gitlab_token`
  (`printf` + `base64 -w0` на stdin), уходит только в env команд `git clone` и `git fetch` (`GIT_CONFIG_COUNT`,
  `GIT_CONFIG_KEY_0=http.<url>.extraHeader`, `GIT_CONFIG_VALUE_0`, `GIT_TERMINAL_PROMPT=0`); `git-askpass.sh` не создаётся,
  старый файл удаляется `rm -f`; `services/sandboxes.bootstrap` передаёт `--gitlab-url` из `config.gitlab.base_url`;
  `services/sandboxes.activate` строит тот же набор через `git_auth_env(base_url, token)` (параметр `gitlab_base_url`),
  dispatcher передаёт адрес из конфига; заголовок и base64 добавлены в redaction (`git_auth_header`) в диспетчере и в CLI —
  проверка: `shellcheck`; `test_sandbox_bootstrap.py`: нет askpass и `GIT_ASKPASS`, заголовок только в строках clone и fetch,
  без `export`, токен через builtin/stdin (не в argv), `--gitlab-url` http → 2, с `@` → 2, с пробелом → 2, без адреса при
  клонах → 2, без токена при клонах → 1 до установок; `test_sandbox_service.py`: env fetch содержит `GIT_CONFIG_KEY_0`
  с префиксом `https://<host>/` и значение, декодирующееся в `oauth2:<token>`; нет `GITLAB_TOKEN` и `GIT_ASKPASS`;
  `test_dispatcher.py`: заголовок в fetch и редакция base64 в выводе агента; `test_cli.py`: редакция заголовка в выводе
  bootstrap; `git_auth_env`/`git_auth_header` — юнит-тесты; защита `HARNESS_SANDBOX_BOOTSTRAP=1`: скрипт без переменной с
  валидными аргументами → код 3, в пустом HOME ничего не создано, заглушки npm/sudo/apt/git/curl/… не вызваны (маркеры
  не появились); ошибки аргументов по-прежнему 2; `services/sandboxes.bootstrap` выставляет переменную (тест env)

## 3. Документация

- [x] 3.1 ARCHITECTURE.md §7 (bootstrap, память, ключи из vault) и §9 (ENV `VAULT_MCP_URL`, `VAULT_MCP_TOKEN`, поля
  `gitlab.access_ref`, `sandbox.memory`); `docs/deployment.md` — ссылки vault, первый bootstrap; `docs/open-questions.md`
  — вопрос 4 (клон при bootstrap) и 6 (шаблон не делаем, D-44); PLAN.md — статус — проверка: ревью диффа
- [x] 3.2 Документация под D-51: ARCHITECTURE.md §7 — `--memory-version`/«`project-memory` точной версии» → «С
  `--memory-ref`/`--memory-repo` (`sandbox.memory`, D-47, D-51): … memory-agent из GitHub на закреплённом коммите
  (`npm install -g github:<repo>#<sha>`, маркер `~/.harness/memory/installed-ref`)»; ARCHITECTURE.md §9 — поля
  `sandbox.memory.repo`, `sandbox.memory.ref` вместо `version`, если `version` там упомянут; `docs/deployment.md` —
  «`project-memory` точной версии» → «memory-agent из GitHub на коммите `sandbox.memory.ref`», пример блока
  `sandbox.memory` с `ref: 09e5e63ac721db75020fcfa69e33930750975139` (закреплённый коммит, D-51) и фразой: обновление
  memory-agent — новый полный sha в `ref` и повторный `harness-server sandbox bootstrap`; пакет `project-memory` из
  реестра npm не ставить (чужой) — проверка: `grep -rn "memory-version\|project-memory\` точной" ARCHITECTURE.md
  docs/deployment.md` — пусто; ревью диффа

## 4. Память проекта харнесса

- [x] 4.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов
- [x] 4.2 То же после 2.5–2.7 и 3.2 (пути из диффа, включая `docs/decisions.md` и этот каталог OpenSpec)

## 5. Live-проверки (владелец, песочница Novita, после ответов на вопросы 1–2)

Новый файл `test_sandbox_profile_live.py` (`-m live`, пропуск без `LIVE_NOVITA_API_KEY`, `LIVE_NOVITA_SANDBOX_ID`,
`LIVE_CLAUDE_CODE_OAUTH_TOKEN`; значения не печатаются). Перед проверками — `harness-server sandbox bootstrap` с
`sandbox.memory` и ссылками на vault; memory-agent ставится с коммита `sandbox.memory.ref` (D-51). Если тест сам
собирает конфиг, sha берётся из ENV `LIVE_MEMORY_REF` (пропуск без него); значение по умолчанию в коде нет, закреплённый
коммит указан в `docs/deployment.md`.

- [ ] 5.1 Двойной bootstrap: второй запуск — код 0, Node, Docker, npm-пакеты не переустанавливаются («уже установлен»),
  в выводе второго запуска `уже установлен: github:<repo>#<ref>`; `cat ~/.harness/memory/installed-ref` равен
  `github:<repo>#<ref>`; `memory --help` от пользователя песочницы — код 0 (бинарь доступен не только root)
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
