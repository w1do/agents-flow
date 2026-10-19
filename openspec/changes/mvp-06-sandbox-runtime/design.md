# Design: mvp-06-sandbox-runtime

## Context

Одна песочница, созданная вручную (ТЗ §16.0 п.7), id в `config/harness.yaml` (`sandbox.provider_id`). Агент может
работать десятки минут, а exec-вызов Novita не должен держать соединение всё это время. Факты API — из
`docs/novita.md` (`mvp-01`) и исследования mvp-06 (интроспекция `novita_sandbox==2.1.1`, документация Claude Code).

Что уже есть: таблицы `sandboxes` и `task_tokens` (миграция `0001`, хранится только `token_hash`), `SandboxStatus`
(`paused`, `active`, `error`) и `AgentRole` (`planner`, `implementer`) в `harness_shared.sandboxes`, ENV
`NOVITA_API_KEY`, `NOVITA_DOMAIN`, `CLAUDE_CODE_OAUTH_TOKEN`, `AGENT_RUN_TIMEOUT_MIN` (по умолчанию 60) в `settings.py`,
`claim_next_task` в `services/tasks.py`, `security/redaction.py`, пустой цикл в `worker.py`.

## Goals / Non-Goals

**Goals:** агент запускается и отслеживается без бинарника в песочнице; креды не остаются на диске; повторная
активация и повторный запуск той же задачи безопасны (рестарт worker); песочница не берёт две задачи.

**Non-Goals:** пул и создание песочниц, перенос задач между песочницами, контроль контекста, учёт бюджета, содержимое
этапов plan/implement (`mvp-08`/`mvp-09`), проверка токена задачи на стороне MCP (`mvp-07`).

## Decisions

1. **SDK — нативный async (D-35).** Адаптер `adapters/novita/client.py` (`NovitaSandboxProvider`) использует
   `novita_sandbox.core.AsyncSandbox`; `asyncio.to_thread` не нужен. Зависимость `novita-sandbox==2.1.1` (точная
   версия) в `apps/server/pyproject.toml`. Если какой-то метод async-класса (`connect`, `pause`, `set_timeout`)
   окажется отсутствующим или с другой сигнатурой — для него и только для него `asyncio.to_thread` над sync
   `Sandbox`, с комментарием причины. Импорт `novita_sandbox` — только в `client.py`. Если у пакета нет `py.typed`,
   в корневом `pyproject.toml` — override `ignore_missing_imports` для `novita_sandbox.*`, а `client.py` типизирует
   границу своими аннотациями. Ключ и домен передаются явно (`api_key=`, `domain=`) из `Settings`, а не через
   глобальный ENV процесса.
2. **Протокол `SandboxProvider`** (`adapters/novita/protocol.py`), все методы async, принимают `sandbox_id`:
   - `connect(sandbox_id)` — подключение; paused возобновляется (`AsyncSandbox.connect`).
   - `exec(sandbox_id, cmd, *, envs=None, cwd=None, timeout_s=60) -> ExecResult(exit_code, stdout, stderr)`; ненулевой
     код (`CommandExitException`) не бросается, а возвращается в `ExecResult`.
   - `write_file(sandbox_id, path, data)`, `read_file(sandbox_id, path) -> str | None` (нет файла → `None`).
   - `pause(sandbox_id)`, `extend_timeout(sandbox_id, seconds)` (`set_timeout`, отсчёт от вызова).
   - Ошибки: `SandboxNotFound` (`SandboxNotFoundException`, а также `TimeoutException` с текстом «sandbox was not
     found» — так Novita отвечает на exec убитой песочницы), `SandboxUnavailable` (`RateLimitException`, прочие
     `SandboxException`, сеть). Исключения адаптера в `adapters/novita/errors.py`, текст без ключа, домена и cmd
     (cmd может содержать пути и токены не содержит, но правило единое с Telegram/Polza: в сообщение — только класс
     и код).
   - `FakeSandbox` (`adapters/novita/fake.py`): файлы в памяти, журнал вызовов `(method, cmd, envs_keys, cwd)` —
     значения env в журнал не пишутся, только ключи, а для тестов «Проверка диска» фейк хранит значения отдельно и
     ищет их в своих файлах; программируемые ответы по префиксу команды; флаг `paused`.
3. **Фоновый запуск + файлы задачи.** Каталог `~/.harness/tasks/<task_id>/`. `run_agent` пишет `prompt.md` и `run.sh`
   (без секретов, все пути через `shlex.quote`), затем одним exec запускает
   `setsid nohup bash run.sh >/dev/null 2>&1 & echo $! > pid` с env-кредами и сразу возвращается. `CommandHandle.pid`
   из `background=True` не используется: handle теряется при рестарте worker, pid-файл — нет. `setsid` делает pid
   лидером группы, чтобы kill по таймауту остановил и дочерние процессы (`kill -TERM -- -<pid>`, через 10 с
   `kill -KILL -- -<pid>`). `run.json` (пишет сервер до запуска): `started_at` (UTC ISO), `max_turns`, `role` — нужен
   для таймаута после рестарта. `run.sh` по завершении атомарно (`tmp` + `mv`) пишет `status.json`:
   `{"exit_code": N, "finished_at": "..."}`. Итог хода (`subtype`, `is_error`, `num_turns`, `session_id`, `usage`)
   сервер берёт из последнего события `type == "result"` в `stream.jsonl` (`tail -n 200`), чистая функция
   `services/agent_result.py::parse_result(lines) -> AgentResult | None`. Worker опрашивает раз в
   `AGENT_POLL_INTERVAL_SEC` (по умолчанию 15). Альтернатива — держать exec до конца: обрыв соединения и
   `timeout=60` по умолчанию у foreground `run` убивают отслеживание.
4. **Команда агента** (в `run.sh`):
   ```
   unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
   cd <worktree>
   claude -p "$(cat <dir>/prompt.md)" --output-format stream-json --verbose --max-turns <N> \
     --permission-mode bypassPermissions --strict-mcp-config --mcp-config ~/.harness/mcp.json \
     --setting-sources user > <dir>/stream.jsonl 2> <dir>/stderr.log
   ```
   `--verbose` обязателен для `stream-json` (mvp-01); `--max-turns` задокументирован в cli-reference (по достижении —
   выход с ошибкой, `subtype: error_max_turns`). `--bare` не используется: он не читает `CLAUDE_CODE_OAUTH_TOKEN`
   (D-18). `unset` — защита от перекрытия токена подписки: по документации Claude Code `ANTHROPIC_AUTH_TOKEN` и
   `ANTHROPIC_API_KEY` имеют приоритет над `CLAUDE_CODE_OAUTH_TOKEN` (D-37).
5. **Изоляция от настроек репозитория (D-36).** Без `--bare` режим `-p` выполняет hooks из `.claude/settings.json`
   и подключает `.mcp.json` рабочего каталога без диалога доверия; репозиторий задачи — недоверенный ввод
   (агент сам меняет его, MR приходят снаружи). Поэтому `--setting-sources user` (не читать project/local
   settings, а значит и их hooks) и `--strict-mcp-config` (только серверы из `~/.harness/mcp.json`). Профиль
   пользователя в песочнице чистый: bootstrap не кладёт hooks, plugins и `~/.claude/settings.json` с hooks.
   `CLAUDE.md` репозитория агент читать должен — это не настройки. Live-тест проверяет: hook из
   `.claude/settings.json` worktree не срабатывает, сервер из `.mcp.json` worktree не подключается
   (`system/init.mcp_servers`).
6. **Креды только в env.** `CLAUDE_CODE_OAUTH_TOKEN`, `AGENTS_FLOW_TOKEN`, `AGENTS_FLOW_URL` — только в env exec
   запуска `run.sh`. `GITLAB_TOKEN` — только в env git-команд (`fetch`, `clone`, `worktree add` при необходимости
   сети) и bootstrap. Git-доступ — через `~/.harness/bin/git-askpass.sh` (пишет bootstrap, без значений: печатает
   `oauth2` на запрос Username и `$GITLAB_TOKEN` на Password) и env `GIT_ASKPASS`, `GIT_TERMINAL_PROMPT=0`.
   `create(envs=)` песочницы не используется: такие env живут всю жизнь песочницы. Персистентность command-env на
   диске документацией не описана — это проверяет live-тест «Проверка диска» (`grep -rF` значения в `~` и worktree,
   исключая `/proc`).
7. **Токен задачи** (`security/tokens.py`): `generate() -> str` (`secrets.token_urlsafe(32)`), `hash_token(token,
   key) -> str` (HMAC-SHA256 с `HARNESS_SECRET_KEY`, hex, 64 символа). Сервис `services/sandboxes.issue_task_token`
   пишет `task_tokens` (роль `planner` для `plan`, `implementer` для `implement`, `expires_at = now +
   AGENT_RUN_TIMEOUT_MIN + 10 мин`) и возвращает значение один раз; `revoke_task_tokens(task_id)` ставит
   `revoked_at` всем активным токенам задачи. Токен выдаётся в `run_agent` (непосредственно перед запуском), а не
   в `activate`: значение не хранится, и после рестарта worker повторная активация иначе не смогла бы его
   передать. Проверка токена — `mvp-07`.
8. **Строка песочницы.** `services/sandboxes.ensure_sandbox(config)` — upsert строки по `provider_id` из конфига
   (`agent_type = "claude-code"`, `status = paused`) при старте worker и в CLI. Песочница в `error` задачи не берёт,
   пока оператор не сделает `sandbox resume` (сбрасывает в `paused` после успешного `connect`).
9. **Резервирование песочницы и задачи одной транзакцией.** `services/sandboxes.reserve(session, pipeline)`:
   `SELECT sandboxes … WHERE current_task_id IS NULL AND status = 'paused' FOR UPDATE SKIP LOCKED`; нет строки — `None`,
   задача остаётся в очереди (сценарий «Песочница занята»). Иначе выбор задачи — та же выборка, что у
   `claim_next_task`: из `services/tasks.py` выделяется публичная `lock_next_task(session, *, kind, from_status,
   to_status | None, source, text) -> Task | None` без commit (документировано: только для композиции внутри
   сервисов; `claim_next_task` = `lock_next_task` + commit, поведение и тесты не меняются). `to_status = None` —
   задача берётся без смены статуса (нужно `plan` в `planning`, mvp-08): тогда выборка исключает задачи, уже
   закреплённые за песочницей (`NOT EXISTS sandboxes.current_task_id = tasks.id`), и пишет событие с текущим
   статусом. Затем `sandbox.current_task_id = task.id`, `status = active`, один commit (D-24).
10. **Идемпотентная активация.** `activate(task, base_ref)`: `connect`, `extend_timeout((AGENT_RUN_TIMEOUT_MIN + 10) *
    60)`, `git fetch origin` в `~/work/<workspace_id>`, и если worktree `~/.harness/worktrees/<task_id>` уже есть
    на ветке `task/<task_id>` — шаг пропускается, иначе `git worktree add -B task/<task_id> <path> <base_ref>`.
    `run_agent` идемпотентен: есть `status.json` — возвращает «уже завершён», есть `pid` и процесс жив
    (`kill -0`) — «уже идёт», агент второй раз не запускается. `pid` есть, а процесса и `status.json` нет — агент
    умер без итога: `AgentRun(exit_code=None, reason="агент завершился без статуса")` → задача `error`.
11. **Каркас пайплайна** (`worker/` становится пакетом: `worker.py` → `worker/__init__.py` без изменения импортов
    `harness_server.worker`, плюс `worker/dispatcher.py`, `worker/pipeline.py`). `Pipeline` (Protocol): `kind`,
    `from_status`, `to_status | None`, `role`, `base_ref(task, config) -> str`, `async run(ctx, task) -> Outcome`.
    Реестр `PIPELINES: dict[TaskKind, Pipeline]` пуст в mvp-06 (реальные регистрируют mvp-08/09), тесты регистрируют
    фейковый. Шаг диспетчера: восстановление (песочница с `current_task_id` → продолжить её задачу с `activate`) →
    `reserve` → `activate` → `pipeline.run` (внутри `ctx.run_agent` + `ctx.wait_agent`) → `cleanup` → `pause`.
    Исключение пайплайна или таймаут → задача `error` через `services.tasks.change_status` (если переход разрешён,
    иначе только событие) с причиной, затем `cleanup`. Новых статусов нет.
12. **Порядок в конце:** `cleanup` (`git worktree remove --force`, `git branch -D task/<id>` локально, удаление
    `~/.harness/tasks/<id>/` кроме копии итога в БД, `revoke_task_tokens`) → успех → `pause` и `current_task_id =
    NULL`, `status = paused`. Ошибка очистки (ненулевой код любой git-команды) → песочница `error`, причина в лог
    (после redaction), `pause` не вызывается, `current_task_id` остаётся для разбора.
13. **Таймаут агента** `AGENT_RUN_TIMEOUT_MIN`: отсчёт от `run.json.started_at`. По истечении — kill группы, задача
    `error` с причиной «превышено время» (лимит в MVP — сигнал, а не баг, ТЗ §16.0).
14. **Всё, что читается из песочницы** (`stderr.log`, хвост `stream.jsonl`, stdout/stderr exec), проходит
    `redact(text, extra_values=[CLAUDE_CODE_OAUTH_TOKEN, GITLAB_TOKEN, токен задачи, NOVITA_API_KEY])` до лога, БД
    и Telegram. В лог — не больше 2000 символов. Вывод `env`, `printenv`, `/proc/*/environ` не запрашивается.
15. **Лимиты (D-38):** `AGENT_RUN_TIMEOUT_MIN=60` (ENV, есть), `workspaces[].agent_max_turns: int = 50` (1…500) в
    `harness.yaml`, pinned версии в `sandbox`: `claude_code_version: "2.1.292"`, `openspec_version: "1.14.3"`.
    Новый ENV `AGENT_POLL_INTERVAL_SEC` (по умолчанию 15, > 0), `AGENTS_FLOW_URL` берётся из `HARNESS_PUBLIC_URL`
    + `/mcp` (новой переменной нет).
16. **Bootstrap** `deploy/sandbox/bootstrap.sh`: `set -euo pipefail`, идемпотентен; аргументы — версии и пары
    `<workspace_id>=<clone_url>`; ставит `npm install -g @anthropic-ai/claude-code@<v> @fission-ai/openspec@<v>`
    только если установленная версия отличается; создаёт `~/.harness/{bin,tasks,worktrees}`, `~/work`;
    `git-askpass.sh` (0700); `~/.harness/mcp.json` (`{"mcpServers": {"agents-flow": {"type": "http", "url":
    "${AGENTS_FLOW_URL}", "headers": {"Authorization": "Bearer ${AGENTS_FLOW_TOKEN}"}}}}` — плейсхолдеры, Claude
    Code раскрывает их из env); клон — только если каталога нет, иначе `git remote set-url` + `fetch`. Clone URL —
    `{gitlab.base_url}/{gitlab_project}.git`. CLI `harness-server sandbox bootstrap` пишет скрипт через
    `write_file` и выполняет с env `GITLAB_TOKEN`, `GIT_ASKPASS`. Скрипт проверяется `shellcheck`
    (dev-зависимость `shellcheck-py`, шаг в `./tools/harness check`).
17. **Исходящий allowlist.** Novita поддерживает `network.allow_out/deny_out` и `set_network` (IP/CIDR; доменные
    имена в core SDK не подтверждены). В MVP песочница создаётся вручную, поэтому ограничение — рекомендация в
    `docs/deployment.md` и пункт live-проверки, а не код. Код создания песочниц — `sandbox-pool`.

## Risks / Trade-offs

- [Novita по умолчанию уничтожает песочницу по таймауту вместе с данными (D-19)] → на `activate`
  `extend_timeout(AGENT_RUN_TIMEOUT_MIN + 10 мин)`; полноценное продление — `sandbox-timeout-extend`.
- [Пауза сохраняет файлы и процессы (mvp-01, один короткий цикл)] → порядок `cleanup` → `pause` ради чистоты
  состояния; долгая пауза не проверена.
- [Лимит команды Novita 10 vCPU, рабочая песочница оператора занимает 8] → в MVP одна песочница задач (2 vCPU).
- [`--setting-sources user` может не отключать все источники hooks/MCP проекта, документация не перечисляет
  исключения] → `--strict-mcp-config`, чистый профиль и live-тест с ловушкой-hook; при провале — блокер, решение
  до `mvp-08`.
- [`message_id` в Python SDK общий на ход, а `docs/novita.md` предполагал дедупликацию usage по `message.id`] → итог
  берётся только из `result.usage`; поведение `message.id` на многоходовом запуске фиксирует live-тест, расчёт
  бюджета — `budget-usage`.
- [OAuth-токен подписки доступен процессу агента; агент выполняет произвольный код, исходящий HTTPS открыт →
  возможна экфильтрация (решение пользователя, D-18)] → токен только в env exec `run.sh`; `GITLAB_TOKEN` и
  `AGENTS_FLOW_TOKEN` — только в узкие команды; всё, что уходит из песочницы, проходит redaction (шаблон
  `sk-ant-…` и точное значение), покрыто тестом; токен не пишется в `mcp.json`, `git-askpass.sh`, `run.sh`,
  `run.json`, `status.json`; токен хранится только в ENV Dokploy; ротация не реже 90 дней и сразу при подозрении;
  рекомендуется отдельный аккаунт или подписка под харнесс; allowlist исходящего трафика — рекомендация
  (решение 17).
- [`/proc/<pid>/environ` агента читаем внутри песочницы] → принято: агент и так владеет токеном; сервер такие пути
  не читает.
- [Лимиты подписки по окнам использования; `total_cost_usd` условен] → бюджет задач (`task-limits`) учитывает
  токены из `usage`, а не только USD (вопрос 8).
- [Сигнатуры async `connect`/`pause`/`set_timeout` не сверены] → решение 1: точечный fallback на `to_thread`.
