# Harness

Go-бинарник для Linux, подключающий Git-проект к Agents Flow. Своей БД,
очереди и web-сервера нет. Работу агента выполняет внешний runner.
Подробности: [harness/README.md](../harness/README.md),
[контракт runner](../harness/RUNNER.md), [runner/README.md](../runner/README.md).

## Установка и команды

Нужны Go 1.24+, Git, непривилегированная учётная запись, доступный `/proc`
и Linux `PR_SET_CHILD_SUBREAPER`. Supervisor включает `no_new_privs`.
Другие ОС и root для `run` не поддерживаются.

```bash
cd harness
go build -o /tmp/harness ./cmd/harness
cd /path/to/project
/tmp/harness init <project_id> --server-url https://flow.example.com --agent-name my-agent
/tmp/harness run
```

Init-код передаётся интерактивно или через `AGENTS_FLOW_INIT_TOKEN`.
Адрес сервера также берётся из `AGENTS_FLOW_SERVER_URL`. HTTPS обязателен,
HTTP допустим для loopback или с явным `--allow-insecure`/`allow_insecure`.

## Что делает init

1. Находит корень Git-проекта и URL `origin`, если remote существует.
2. Отправляет `POST /harness/init` с init-кодом.
3. Получает одноразово agent-токен и skills.
4. Создаёт `workflow/{config.yaml,.gitignore,.agent-token,skills/}`.

Токен хранится только в `.agent-token`, права 0600; файл игнорируется Git.
В YAML токена нет. Существующий `workflow/` не перезаписывается.

## Конфигурация

```yaml
server_url: https://flow.example.com
project_id: "uuid"
agent_id: "uuid"
workspace_path: "/absolute/path/to/project"
git_remote: "origin"
poll_interval_seconds: 5
lease_ttl_seconds: 60
runner:
  command: ["/absolute/path/to/runner/.venv/bin/agents-flow-runner"]
  timeout_seconds: 1800
  decision_timeout_seconds: 3600
  environment:
    AGENT_PROVIDER: stub
```

Runner задаётся явно массивом аргументов, без shell-подстановок.
Относительное имя с `/` разрешается от workspace_path, иначе используется PATH.
Отсутствующие/нулевые таймауты означают 1800 и 3600 секунд соответственно.
Для Python runner нужны Python >=3.11 и editable install:

```bash
cd /absolute/path/to/runner
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/python -m runner --help
AGENT_PROVIDER=stub .venv/bin/python examples/smoke.py
```

Stub работает без API. AGENT_PROVIDER=deepagents использует Deep Agents SDK.
Явный AGENT_PROVIDER=openai-compatible выбирает совместимый API-адаптер.
Ключ/endpoint/model читаются из явного environment (приоритет) или файла
AGENT_FLOW_RUNNER_ENV_FILE, по умолчанию $HOME/.config/agents-flow/runner.env
с правами не шире 0600. Формат: OPENAI_API_KEY=..., OPENAI_BASE_URL=...,
AGENT_MODEL=.... Harness runner передаёт только PATH/HOME/LANG/TZ/TERM.
Конфигурация строится и проверяется без сети.

## Цикл run

1. Синхронизировать skills до новой задачи, проверить доступ, арендовать задачу.
2. Создать или переиспользовать worktree с веткой `task/<task_id>`.
3. Planning → ожидание решения → implementation → testing → ожидание результата.
4. Rework повторяет реализацию и проверки с feedback; keep_ready продолжает ожидание.
5. После подтверждённого publish (merged + publication_requested) запустить publication.

До каждого этапа harness проверяет execution-state и lease. Пока ждёт решение,
runner не запущен; heartbeat продолжается. Основная копия проекта не меняется.
Skills синхронизируются только между задачами: новые скачиваются, изменённые
обновляются, снятые удаляются; снимки выполняемой задачи остаются прежними.
Planning/implementation получают непубликационные skills, testing — test/testing,
publication — git/deploy. Категория берётся из category либо имени файла.
Без skills публикации push/deploy не выполняются.

## Runner stdin/stdout

Один процесс — один этап; CWD, `path`, `worktree` указывают на worktree задачи.
На stdin передаются task, stage, path, worktree, branch, read_only, checkpoint,
skills со снимками content; при необходимости plan_text, feedback и result_data.
На stdout — NDJSON, одна строка до 1 МиБ:

```json
{"type":"plan","plan_text":"Human-readable plan"}
{"type":"progress","message":"Saved","payload":{"step":1},"checkpoint":{"cursor":"saved"}}
{"type":"test_result","command":"command from a skill","exit_code":0,"summary":"passed"}
{"type":"result","result_summary":"Implemented","result_data":{"changed_paths":["file"]}}
{"type":"failure","message":"Runner failure","checkpoint":{"cursor":"saved"}}
```

Planning требует read_only и ровно одного plan. Остальные этапы — одного result,
exit 0; publication result обязательно содержит success и message. Failure,
ненулевой exit, некорректный JSON или terminal вызывают отчёт о сбое.
Harness агрегирует test_result в result_data.tests; progress payload становится
details, checkpoint сохраняется сразу и передаётся следующему процессу.
Stub меняет runner-stub.txt на implementation; testing запускает fenced-блоки
skills через bubblewrap. Корень read-only, worktree writable, /tmp и /home
изолированы tmpfs, сеть и PID namespace отключены, capabilities сброшены.
Системные файлы, например /etc/passwd, остаются читаемыми из read-only bind.
Без bwrap команды fail-closed с sandbox_unavailable. sh/пустой язык, bash и
python/python3 поддержаны; прочие языки дают unsupported_language.
Процессы запускаются в отдельной сессии и убиваются вместе с потомками по таймауту.
Deepagents использует SDK; файловый доступ runner основан на directory descriptors,
O_NOFOLLOW и атомарной замене относительно открытых каталогов.
Секреты и их base64-представления маскируются в отчётах.

## Восстановление и ошибки

Журнал и приватные snapshots находятся в `<git-dir>/agents-flow-harness/`.
После перезапуска сохраняются worktree, checkpoint и pending-отчёт с тем же
event_id/Idempotency-Key. Сетевые ошибки повторяются; задачу останавливает
потеря lease (`409`), без новых отчётов по потерянной аренде.
Таймаут ожидания и SIGINT/SIGTERM сохраняют работу для продолжения.
Supervisor останавливает runner и потомков, включая double-fork/setsid.
Сбой публикации передаётся через publication-result с success=false.
Runner stderr и сырые ошибки не выводятся, секреты в отчётах маскируются.

Конфигурация фиксируется при загрузке. Изменение или удаление config.yaml,
в том числе во время ожидания задачи, завершает harness невосстанавливаемой
ошибкой `config changed, restart harness`; повторов нет, нужен перезапуск.
Host runner готовит индекс без clean/smudge, проверяет staged blob и типы записей;
пустой staged diff возвращает `success:true, commit_sha:null, no_changes:true`.
Модель и sandbox не видят `.secrets`, `.env*`, `*.env`, `*.pem`, `*.key`,
`id_rsa*`, `.npmrc`, `.pypirc`, `.git`, `.agent-token`.
Git verification не содержит subject и сырых строк status; защищённые пути скрыты.
Сервер хранит эти сведения только как `claims` с `source:"agent_reported"`;
они не влияют на статус/приёмку. commit_sha сохраняется и без verification.

Все Git-команды harness изолированы от унаследованных Git-переменных и system/global config.
Hooks, fsmonitor, подписи и внешние filter-драйверы отключены; clean/smudge заменены на cat.
Новый worktree создаётся через `worktree add --no-checkout`, затем безопасный checkout.
Runner проверяет и коммитит приватную копию индекса, сохраняя реальный индекс побайтно.
После commit verification сравнивает worktree с HEAD через отдельный индекс;
обычный git status может показывать расхождение сохранённого реального индекса с новым HEAD.
Пути проверяются через casefold; переход на другой st_dev отклоняется как `mount_crossing`.
