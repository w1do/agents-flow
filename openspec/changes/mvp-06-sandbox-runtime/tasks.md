# Tasks

Решения — `design.md` (пункты 1–18) и `docs/decisions.md` D-35…D-38, D-41, D-42. Пути ниже — от `apps/server/src/harness_server/`,
тесты — `apps/server/tests/`.

## 1. Адаптер песочницы

- [x] 1.1 `novita-sandbox==2.1.1` в `apps/server/pyproject.toml`, `uv lock`; при отсутствии `py.typed` — override
  `ignore_missing_imports` для `novita_sandbox.*` в корневом `pyproject.toml` (с комментарием) — проверка: `uv sync`, mypy
- [x] 1.2 `adapters/novita/{__init__,protocol,errors,client}.py`: Protocol `SandboxProvider` (`connect`, `exec` →
  `ExecResult`, `write_file`, `read_file` → `str | None`, `pause`, `extend_timeout`), `NovitaSandboxProvider` на
  `AsyncSandbox` (design 1–2), маппинг исключений в `SandboxNotFound`/`SandboxUnavailable` без секретов в тексте — проверка:
  mypy; `test_novita_client.py` с подменой `AsyncSandbox` (monkeypatch): ненулевой код → `ExecResult`, «sandbox was not
  found» → `SandboxNotFound`, нет файла → `None`, текст ошибки без ключа
- [x] 1.3 `adapters/novita/fake.py` `FakeSandbox`: файлы в памяти, журнал `(method, cmd, env_keys, cwd)`, значения env
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
- [x] 2.2 `config.py`: `SandboxConfig.claude_code_version = "2.1.292"`, `openspec_version = "1.14.3"`,
  `WorkspaceConfig.agent_max_turns: int = 50` (1…500); `config/harness.example.yaml` — проверка: `test_config.py`
- [x] 2.3 `harness-server sandbox bootstrap` — `services/sandboxes.bootstrap` пишет скрипт через `write_file` и выполняет с
  аргументами из конфига и env `GITLAB_TOKEN`, `GIT_ASKPASS` — проверка: тест с фейком (команда и аргументы в журнале,
  в записанном скрипте нет значения `GITLAB_TOKEN`)

## 3. Сервис песочниц

- [x] 3.1 `security/tokens.py`: `generate`, `hash_token` (HMAC-SHA256 с `HARNESS_SECRET_KEY`); в `services/sandboxes.py`
  `issue_task_token` (роль по kind, `expires_at`), `revoke_task_tokens` — проверка: `test_tokens.py` (в БД только хеш,
  отзыв ставит `revoked_at`)
- [x] 3.2 `services/tasks.py`: выделить `lock_next_task` (без commit, `to_status | None`, исключение задач с
  закреплённой песочницей при `None`); `claim_next_task` = `lock_next_task` + commit — проверка: существующие
  `test_task_queue.py` зелёные без правок, новый тест `to_status=None`
- [x] 3.3 `services/sandboxes.ensure_sandbox`, `reserve` (design 8–9) — проверка: тесты «Песочница занята» (задача B в
  прежнем статусе), «Песочница в ошибке», параллельный `reserve` не берёт одну песочницу
- [x] 3.4 `activate(task, base_ref)`: `connect`, `extend_timeout`, `git fetch`, worktree, идемпотентность — проверка: тест
  «Повторная активация» (второй вызов не пишет `worktree add` в журнал фейка)
- [x] 3.5 `run_agent(task, prompt, role)`: `run.json`, `prompt.md`, `run.sh` (design 3–4, `unset`, флаги изоляции),
  выдача токена, запуск `setsid nohup`, env только для этой команды; идемпотентность по `status.json`/`pid` — проверка:
  тест «Проверка диска» на фейке (значений кредов нет ни в одном записанном файле), тест «агент не запускается второй
  раз», тест: `ANTHROPIC_API_KEY` нет в env ни одной команды
- [x] 3.6 `services/agent_result.py::parse_result` и `poll`/`wait_agent`: `status.json`, хвост `stream.jsonl`, таймаут от
  `started_at` с kill группы и `error` «превышено время», «агент завершился без статуса», redaction `stderr.log` —
  проверка: тесты «Агент завершился», «Превышено время», «Агент пропал без статуса», «Секрет в выводе агента»
- [x] 3.7 `cleanup` + `pause` после успеха; `error` песочницы при неудаче — проверка: тесты «Очистка не удалась»,
  «Успешная очистка»

## 4. Worker и CLI

- [x] 4.1 `worker.py` → пакет `worker/` (`__init__.py` с прежним API, `dispatcher.py`, `pipeline.py`): `Pipeline`,
  реестр по `kind` (пуст), шаг восстановление → reserve → activate → run → cleanup → pause, ошибки → `error` задачи;
  `AGENT_POLL_INTERVAL_SEC` в `settings.py` — проверка: `test_dispatcher.py` с фейковым пайплайном и `FakeSandbox`,
  `test_worker.py` зелёный
- [x] 4.2 `harness-server sandbox pause|resume|status|bootstrap` (тонкий вход, логика в `services/sandboxes`), отказ паузы
  при активной задаче, `resume` сбрасывает `error` → `paused` после успешного `connect` — проверка: тест «Пауза занятой
  песочницы» в `test_cli.py`
- [x] 4.3 Документация: ARCHITECTURE.md §2 (worker/, adapters/novita), §7, §9 (`AGENT_POLL_INTERVAL_SEC`,
  `CLAUDE_CODE_OAUTH_TOKEN`, `AGENT_RUN_TIMEOUT_MIN`), `.env.example`, `docs/deployment.md` (bootstrap, allowlist,
  ротация токена), `apps/server/README.md` (структура, live-тест), PLAN.md — проверка: ревью

## 5. Память проекта

- [x] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status`
  без устаревших файлов

## 6. Исправления после ревью

Решения — design 3, 7, 8, 10, 12–14, 18 и D-41, D-42. Выполнять по порядку. Разрешено менять только файлы из
списка ниже; любой другой файл — остановиться и вернуть вопрос оркестратору.

Allowlist: `.gitignore` (только добавить строку), `db/migrations/versions/20261019_0004_sandbox_agent_run.py` (новый),
`apps/server/src/harness_server/db/models/sandboxes.py`, `apps/server/src/harness_server/security/tokens.py`,
`apps/server/src/harness_server/security/redaction.py`, `apps/server/src/harness_server/services/agent_result.py`,
`apps/server/src/harness_server/services/sandboxes.py`, `apps/server/src/harness_server/worker/dispatcher.py`,
`apps/server/tests/test_migrations.py`, `apps/server/tests/test_tokens.py`, `apps/server/tests/test_redaction.py`,
`apps/server/tests/test_sandbox_service.py`, `apps/server/tests/test_dispatcher.py`, `apps/server/tests/test_cli.py`
(только если существующий тест ломается), `ARCHITECTURE.md` (колонки `sandboxes`, семантика `sandbox resume`),
этот `tasks.md` (отметки `[x]`).

- [x] 6.1 (G1) `.gitignore`: добавить в конец строку `.idea/`; остальные строки файла (правки владельца) не трогать —
  проверка: `git diff .gitignore` показывает только добавленную строку `.idea/` поверх правок владельца
- [x] 6.2 (S2, миграция) Новый файл `db/migrations/versions/20261019_0004_sandbox_agent_run.py` по образцу `0003`:
  docstring `"""sandboxes: время запуска и pid агента на сервере (mvp-06, D-41)."""`, `revision = "0004"`,
  `down_revision = "0003"`; `upgrade`: `op.add_column("sandboxes", sa.Column("agent_started_at",
  sa.DateTime(timezone=True), nullable=True))`, `op.add_column("sandboxes", sa.Column("agent_pid", sa.Integer(),
  nullable=True))`; `downgrade`: `op.drop_column` обеих в обратном порядке. В `db/models/sandboxes.py` в `Sandbox`
  после `profile_version`: `agent_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
  nullable=True)`, `agent_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)` (импорт `Integer`);
  docstring класса дополнить: «agent_started_at и agent_pid — серверный учёт запуска агента, файлам песочницы не
  доверяем (D-41)» — проверка: `test_alembic_check_reports_no_diff` и `test_downgrade_and_upgrade_roundtrip`
  зелёные; новый `test_sandboxes_agent_columns_after_0004` в `test_migrations.py` (по образцу
  `test_routings_schema_after_0003`): обе колонки есть и nullable
- [x] 6.3 (N1) `services/agent_result.py::parse_pid`: возвращать `value if value > 1 else None`; docstring: «pid ≤ 1
  отвергается: `kill -0 -- -1` проверяет все процессы пользователя и всегда успешен, 0 — группа вызывающего». В
  `services/sandboxes.py` `_is_alive` при `pid <= 1` возвращает `False` без exec, `_kill_group` при `pid <= 1`
  ничего не делает (защита для значения из БД) — проверка: в `test_sandbox_service.py`
  `test_parse_pid_rejects_non_positive_and_one` (параметры `"0"`, `"1"`, `"-5"`, `"abc"`, `""` → `None`; `"2"` → 2,
  `" 4242\n"` → 4242); `test_is_alive_skips_exec_for_pid_one` (журнал фейка без `kill -0`)
- [x] 6.4 (S3) `security/tokens.py`: константа `TOKEN_PREFIX: Final = "aft_"`, `generate()` возвращает
  `TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)`; docstring модуля: префикс нужен шаблону redaction, хеш —
  от значения целиком (D-42). `security/redaction.py` в `_PATTERNS` после строки `sk-ant-`:
  `(re.compile(r"\baft_[A-Za-z0-9_-]{40,}"), REDACTED),  # токен задачи агента (D-42)` — проверка: `test_tokens.py`
  `test_generated_token_has_prefix` (`startswith("aft_")`, `len >= 44`, `re.fullmatch(r"aft_[A-Za-z0-9_-]{40,}",
  token)`); существующий `test_generated_tokens_are_random_and_url_safe` зелёный без правок; `test_redaction.py`
  `test_redacts_task_token_without_extra_values` (`redact(f"err {tokens.generate()} end")` == `"err [REDACTED] end"`)
  и `test_short_aft_word_is_kept` (`"aft_short"` не меняется)
- [x] 6.5 (S2, сервис) `services/sandboxes.py`:
  - dataclass `AgentRunInfo(frozen=True, slots=True)`: `started_at: datetime | None`, `pid: int | None`; функция
    `async def agent_run_info(session, provider_id: str) -> AgentRunInfo` — `select(Sandbox)` по `provider_id`
    (нет строки — `SandboxStepError("sandbox_not_registered")`), затем `await session.commit()` (транзакция не
    остаётся открытой на время exec); `async def record_agent_pid(session, provider_id: str, pid: int) -> None` —
    `_locked_sandbox`, `agent_pid = pid`, commit; `async def _record_agent_started(session, provider_id: str,
    started_at: datetime) -> None` — `_locked_sandbox`, `agent_started_at = started_at`, `agent_pid = None`, commit.
  - `reserve`: рядом с `current_task_id = task.id` поставить `agent_started_at = None`, `agent_pid = None`.
    `release_sandbox`: рядом с `current_task_id = None` — то же.
  - `run_agent` (design 10, 18), порядок: `home`, `directory`; `info = await agent_run_info(session, provider_id)`.
    Если `info.started_at is not None`: `pid = info.pid`; если `pid is None` — прочитать файл `pid`, `parse_pid`,
    и при не-`None` `record_agent_pid`; `pid is not None and await _is_alive(...)` → `ALREADY_RUNNING`; иначе есть
    `status.json` → `ALREADY_FINISHED`; иначе `DIED`. Если `info.started_at is None`, но есть файл `pid` или
    `status.json` — `DIED` без запуска (файлы без серверной записи не доверяются). Иначе запуск: `role =
    _ROLE_BY_KIND.get(task.kind)`, `None` → `UnsupportedKind(task.kind)` до записи файлов; `run.json` =
    `{"started_at", "max_turns", "role": str(role), "task_id"}` (A1: design и код совпадают, файл только для
    человека); `prompt.md`, `run.sh` как сейчас; `issue_task_token(...)`; `_record_agent_started(session,
    provider_id, started_at)`; команда запуска: `setsid nohup bash <run.sh> >/dev/null 2>&1 < /dev/null & pid=$!;
    echo "$pid" > <pidfile>; echo "$pid"` (пути через `shlex.quote`); `pid = parse_pid(result.stdout)`, `None` →
    `SandboxStepError("launch_pid")`; `record_agent_pid`; вернуть `STARTED` с токеном. Docstring обновить.
  - `wait_agent`: новая сигнатура `wait_agent(provider, provider_id, task, *, started_at: datetime | None, pid: int |
    None, timeout_min: int, now: datetime, secrets: Sequence[str]) -> AgentRun`; `run.json` и файл `pid` не читает.
    Порядок: `started_at is None` → `AgentRun(state=DIED, reason="агент не запущен")` без exec; чтение хвостов
    stderr/stream и `parse_result` как сейчас; `alive = pid is not None and await _is_alive(...)`; `alive` и
    `now - started_at > timedelta(minutes=timeout_min)` → `_kill_group(pid)`, `TIMED_OUT` «превышено время»;
    `alive` → `RUNNING` (даже при наличии `status.json`); не `alive` и есть `status.json` → `FINISHED` как сейчас;
    иначе `DIED` «агент завершился без статуса». Удалить `_parse_started_at` (не используется). Docstring: файлы
    песочницы — подсказка, время и pid — из БД (D-41).
  - проверка (`test_sandbox_service.py`, фейк: `fake.respond("setsid nohup", stdout="4242\n")` для запусков;
    существующие тесты `wait_agent` перевести на явные `started_at=`/`pid=`, `_seed_run` больше не нужен для времени):
    `test_run_agent_records_started_at_and_pid` (строка: `agent_started_at == now`, `agent_pid == 4242`; `run.json`
    содержит `"role": "implementer"` и `task_id`); `test_run_agent_invalid_launch_pid_raises` (stdout `""` →
    `SandboxStepError`, `reason == "launch_pid"`, `agent_started_at` заполнен); `test_run_agent_recovers_pid_from_file`
    (`agent_started_at` задан, `agent_pid` пуст, файл `pid` = `4242`, группа жива → `ALREADY_RUNNING`,
    `agent_pid == 4242`); `test_run_agent_pid_one_in_file_is_died` (файл `1` → `DIED`, в журнале нет `kill -0 -- -1`);
    `test_run_agent_files_without_db_record_not_relaunched` (`agent_started_at` пуст, файл `pid` есть → `DIED`, в
    журнале нет `setsid`); `test_wait_agent_ignores_forged_run_json` (`run.json` со `started_at` в будущем, серверный
    `started_at` старше лимита, `pid=4242` жив → `TIMED_OUT`, в журнале `kill -TERM -- -4242`);
    `test_wait_agent_uses_server_pid_not_file` (файл `pid` = `999`, `pid=4242`, `fake.respond("kill -0 -- -4242",
    exit_code=1)`, есть `status.json` → `FINISHED`, в журнале нет `-999`); `test_wait_agent_status_with_alive_group_is_running`
    (`status.json` с кодом 0, группа жива, время в лимите → `RUNNING`); `test_reserve_and_release_reset_agent_columns`
    (заранее заполненные колонки → после `reserve` и после `release_sandbox` обе `None`); существующие «Агент
    завершился», «Превышено время», «Агент пропал без статуса», «Проверка диска», «агент не запускается второй раз»
    зелёные после перевода на новую сигнатуру
- [x] 6.6 (S2, S4, N2, диспетчер) `worker/dispatcher.py`:
  - `_Runner.wait_agent`: в каждой итерации цикла сначала `async with self._ctx.session_factory() as session: info =
    await sandboxes.agent_run_info(session, self._provider_id)`, затем вне сессии `sandboxes.wait_agent(...,
    started_at=info.started_at, pid=info.pid, ...)`.
  - `_run_reserved`: удалить ветку `except BaseException` целиком (S4: отмена не отзывает токены; этим же снимается
    N2 — подменять исходное исключение больше нечему). Над блоком `try` комментарий: «Отмена worker (BaseException)
    пробрасывается без очистки и без отзыва токенов: агент продолжает работать, _recover продолжит задачу, cleanup
    отзовёт токены (D-41).» Docstring модуля дополнить той же мыслью одной фразой.
  - проверка (`test_dispatcher.py`): `test_cancelled_pipeline_revokes_task_tokens` заменить на
    `test_cancelled_pipeline_keeps_task_tokens` (после `CancelledError` у всех токенов задачи `revoked_at is None`,
    песочница `active`, `current_task_id` = задача, `agent_started_at` не пуст); новый
    `test_recovery_after_cancel_revokes_tokens_on_cleanup` (тот же сценарий, затем `dispatch_once` с пайплайном, где
    агент завершается → токены отозваны, песочница `paused`); тесты восстановления «живой и мёртвый pid» заполняют
    `agent_started_at`/`agent_pid` в строке песочницы вместо `run.json`/`pid` и остаются зелёными
- [x] 6.7 (N3) `services/sandboxes.py` docstring `AgentStartState`: добавить абзац «Вызывающий код на DIED обязан
  вызвать wait_agent, а не переводить задачу в error сразу: между проверками агент мог завершиться штатно, и
  wait_agent вернёт FINISHED (design 10).» — проверка: ревью
- [x] 6.8 (A2) `cleanup_task`: `home = await _home(...)` вызывать всегда; git-команды (`worktree remove`, `branch -D`)
  — только при `task.workspace_id is not None`; `rm -rf <task_dir>` — всегда, последним; обработка ненулевого кода
  прежняя для всех команд. Docstring: «каталог задачи удаляется всегда» — проверка:
  `test_cleanup_without_workspace_removes_task_dir` (задача с `workspace_id=None`: в журнале есть `rm -rf
  <task_dir>`, нет `git -C`; токены отозваны); существующие «Очистка не удалась», «Успешная очистка» зелёные
- [x] 6.9 (A3) `resume_sandbox` (design 8): `_locked_sandbox`; `current_task_id` не пуст → `SandboxBusy` (как сейчас);
  `status == PAUSED` → лог `sandbox resume skipped: already paused provider_id=%s`, `await session.commit()`, return
  без вызовов провайдера; иначе (`ERROR` или `ACTIVE` без задачи; для `ACTIVE` — `logger.warning("sandbox
  desync: active without task provider_id=%s", ...)`) `provider.connect`, `provider.pause`, `status = PAUSED`,
  `agent_started_at = None`, `agent_pid = None`, commit. Ошибка провайдера пробрасывается, строка не меняется.
  Docstring по design 8 — проверка (`test_sandbox_service.py`): `test_resume_error_connects_pauses_and_frees`
  (журнал: `connect`, затем `pause`; статус `paused`; колонки `None`; `fake.paused`);
  `test_resume_paused_is_noop` (журнал фейка пуст); `test_resume_active_without_task_repairs` (статус `paused`);
  существующий отказ при закреплённой задаче зелёный; `test_cli.py` без правок
- [x] 6.10 Документация: `ARCHITECTURE.md` — в описании таблицы `sandboxes` колонки `agent_started_at`,
  `agent_pid` (D-41); у команды `sandbox resume` — семантика из design 8 (из `error` — connect + pause, из `paused` —
  без действий, с задачей — отказ). Других документов не менять — проверка: ревью
- [x] 6.11 Проверки: `./tools/harness check` (ruff check, ruff format --check, mypy --strict, pytest) зелёный;
  `openspec validate mvp-06-sandbox-runtime --strict` — valid; отметить 6.1–6.11 `[x]`. Вернуть оркестратору список
  изменённых и новых путей для memory-sync (Phase 5)
- [x] 6.12 Live-тест рантайма агента (`-m live`, те же `LIVE_*`, пропуск без них): на настоящей песочнице сервисный путь
  `activate` → `run_agent` → `wait_agent` → `cleanup_task` с реальным Postgres. Репозиторий workspace — локальный git
  в песочнице, созданный тестом (без GitLab). Короткая задача, `max_turns` небольшой. Проверить: команда запуска
  отдаёт pid (`agent_pid` и `agent_started_at` в БД), prompt доходит через stdin, `_is_alive` (`kill -0` по группе)
  видит живого агента во время работы, итог `FINISHED`, после `cleanup_task` токены отозваны, worktree и каталог
  задачи удалены, ветка `task/<id>` удалена. Второй сценарий: агент убит до завершения (kill группы), без
  `status.json` → `wait_agent` даёт `DIED`, повторного запуска нет — проверка: `pytest -m live` зелёный у владельца
