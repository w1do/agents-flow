# Tasks

Решения — `design.md` (пункты 1–17) и `docs/decisions.md` D-35…D-38. Пути ниже — от `apps/server/src/harness_server/`,
тесты — `apps/server/tests/`.

## 1. Адаптер песочницы

- [ ] 1.1 `novita-sandbox==2.1.1` в `apps/server/pyproject.toml`, `uv lock`; при отсутствии `py.typed` — override
  `ignore_missing_imports` для `novita_sandbox.*` в корневом `pyproject.toml` (с комментарием) — проверка: `uv sync`, mypy
- [ ] 1.2 `adapters/novita/{__init__,protocol,errors,client}.py`: Protocol `SandboxProvider` (`connect`, `exec` →
  `ExecResult`, `write_file`, `read_file` → `str | None`, `pause`, `extend_timeout`), `NovitaSandboxProvider` на
  `AsyncSandbox` (design 1–2), маппинг исключений в `SandboxNotFound`/`SandboxUnavailable` без секретов в тексте — проверка:
  mypy; `test_novita_client.py` с подменой `AsyncSandbox` (monkeypatch): ненулевой код → `ExecResult`, «sandbox was not
  found» → `SandboxNotFound`, нет файла → `None`, текст ошибки без ключа
- [ ] 1.3 `adapters/novita/fake.py` `FakeSandbox`: файлы в памяти, журнал `(method, cmd, env_keys, cwd)`, значения env
  отдельно для проверки диска, программируемые ответы по префиксу команды, флаг `paused` — проверка: используется в
  тестах ниже
- [ ] 1.4 `test_novita_live.py` (`-m live`, пропуск без `LIVE_NOVITA_API_KEY`, `LIVE_NOVITA_SANDBOX_ID`,
  `LIVE_CLAUDE_CODE_OAUTH_TOKEN`): exec, write/read, pause/connect; многоходовой `claude -p --output-format stream-json
  --verbose` с tool-use — `result.usage` и поведение `message.id` (записать в отчёт), `--max-turns 1` на задаче из
  нескольких ходов → `subtype: error_max_turns`; изоляция (design 5): hook-ловушка в `.claude/settings.json` и сервер в
  `.mcp.json` worktree не срабатывают; «Проверка диска»: `grep -rF` значения токена в `~` и worktree пусто — проверка:
  проходит вручную, запускает и закрывает владелец

## 2. Bootstrap

- [ ] 2.1 `deploy/sandbox/bootstrap.sh` (design 16): `set -euo pipefail`, pinned `claude`/`openspec` через `npm -g` только
  при другой версии, `~/.harness/{bin,tasks,worktrees}`, `~/work`, `git-askpass.sh` (0700, без значений), `mcp.json` с
  `${AGENTS_FLOW_URL}`/`${AGENTS_FLOW_TOKEN}`, клон `<id>=<url>` только если каталога нет, иначе `set-url` + `fetch` —
  проверка: `shellcheck` (dev-зависимость `shellcheck-py`, шаг в `./tools/harness check`); двойной запуск в песочнице без
  ошибок — вручную, владелец
- [ ] 2.2 `config.py`: `SandboxConfig.claude_code_version = "2.1.292"`, `openspec_version = "1.14.3"`,
  `WorkspaceConfig.agent_max_turns: int = 50` (1…500); `config/harness.example.yaml` — проверка: `test_config.py`
- [ ] 2.3 `harness-server sandbox bootstrap` — `services/sandboxes.bootstrap` пишет скрипт через `write_file` и выполняет с
  аргументами из конфига и env `GITLAB_TOKEN`, `GIT_ASKPASS` — проверка: тест с фейком (команда и аргументы в журнале,
  в записанном скрипте нет значения `GITLAB_TOKEN`)

## 3. Сервис песочниц

- [ ] 3.1 `security/tokens.py`: `generate`, `hash_token` (HMAC-SHA256 с `HARNESS_SECRET_KEY`); в `services/sandboxes.py`
  `issue_task_token` (роль по kind, `expires_at`), `revoke_task_tokens` — проверка: `test_tokens.py` (в БД только хеш,
  отзыв ставит `revoked_at`)
- [ ] 3.2 `services/tasks.py`: выделить `lock_next_task` (без commit, `to_status | None`, исключение задач с
  закреплённой песочницей при `None`); `claim_next_task` = `lock_next_task` + commit — проверка: существующие
  `test_task_queue.py` зелёные без правок, новый тест `to_status=None`
- [ ] 3.3 `services/sandboxes.ensure_sandbox`, `reserve` (design 8–9) — проверка: тесты «Песочница занята» (задача B в
  прежнем статусе), «Песочница в ошибке», параллельный `reserve` не берёт одну песочницу
- [ ] 3.4 `activate(task, base_ref)`: `connect`, `extend_timeout`, `git fetch`, worktree, идемпотентность — проверка: тест
  «Повторная активация» (второй вызов не пишет `worktree add` в журнал фейка)
- [ ] 3.5 `run_agent(task, prompt, role)`: `run.json`, `prompt.md`, `run.sh` (design 3–4, `unset`, флаги изоляции),
  выдача токена, запуск `setsid nohup`, env только для этой команды; идемпотентность по `status.json`/`pid` — проверка:
  тест «Проверка диска» на фейке (значений кредов нет ни в одном записанном файле), тест «агент не запускается второй
  раз», тест: `ANTHROPIC_API_KEY` нет в env ни одной команды
- [ ] 3.6 `services/agent_result.py::parse_result` и `poll`/`wait_agent`: `status.json`, хвост `stream.jsonl`, таймаут от
  `started_at` с kill группы и `error` «превышено время», «агент завершился без статуса», redaction `stderr.log` —
  проверка: тесты «Агент завершился», «Превышено время», «Агент пропал без статуса», «Секрет в выводе агента»
- [ ] 3.7 `cleanup` + `pause` после успеха; `error` песочницы при неудаче — проверка: тесты «Очистка не удалась»,
  «Успешная очистка»

## 4. Worker и CLI

- [ ] 4.1 `worker.py` → пакет `worker/` (`__init__.py` с прежним API, `dispatcher.py`, `pipeline.py`): `Pipeline`,
  реестр по `kind` (пуст), шаг восстановление → reserve → activate → run → cleanup → pause, ошибки → `error` задачи;
  `AGENT_POLL_INTERVAL_SEC` в `settings.py` — проверка: `test_dispatcher.py` с фейковым пайплайном и `FakeSandbox`,
  `test_worker.py` зелёный
- [ ] 4.2 `harness-server sandbox pause|resume|status|bootstrap` (тонкий вход, логика в `services/sandboxes`), отказ паузы
  при активной задаче, `resume` сбрасывает `error` → `paused` после успешного `connect` — проверка: тест «Пауза занятой
  песочницы» в `test_cli.py`
- [ ] 4.3 Документация: ARCHITECTURE.md §2 (worker/, adapters/novita), §7, §9 (`AGENT_POLL_INTERVAL_SEC`,
  `CLAUDE_CODE_OAUTH_TOKEN`, `AGENT_RUN_TIMEOUT_MIN`), `.env.example`, `docs/deployment.md` (bootstrap, allowlist,
  ротация токена), `apps/server/README.md` (структура, live-тест), PLAN.md — проверка: ревью

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов
