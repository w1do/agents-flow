# Agents Flow runner

Python >=3.11, bubblewrap (bwrap) для команд skills. Один процесс читает один JSON из stdin и обслуживает один этап.
Источник контракта — [harness/RUNNER.md](../harness/RUNNER.md).
stub не требует API. Provider deepagents использует Deep Agents SDK;
openai-compatible оставлен как явный тонкий адаптер совместимого API.

## Установка и офлайн-проверки

Из корня этого репозитория:

```bash
cd runner
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q tests/test_protocol.py tests/test_stub_agent.py tests/test_deepagents_config.py
.venv/bin/python -m runner --help
.venv/bin/agents-flow-runner --help
AGENT_PROVIDER=stub .venv/bin/python examples/smoke.py
```

Smoke создаёт временный Git-репозиторий и worktree, запускает три отдельных
процесса (planning → implementation → testing), печатает настоящий NDJSON
и проверяет неизменность основной копии. Временные каталоги удаляются.
Тесты запрещают сетевые подключения; внешний API подменяется адаптером.

## Подключение к harness

В `workflow/config.yaml` проекта задайте абсолютный путь к установленному скрипту:

```yaml
runner:
  command: ["/absolute/path/to/runner/.venv/bin/agents-flow-runner"]
  timeout_seconds: 1800
  decision_timeout_seconds: 3600
  environment:
    AGENT_PROVIDER: stub
```

Harness запускает процесс из worktree и передаёт stdin. Python-модуль также
работает из любого каталога после editable install: `/absolute/.venv/bin/python -m runner`.
Доступ к серверу, lease, решения пользователя и выбор skills остаются в harness.

## Вход и события

```json
{"task":{"id":"task-id","title":"Task"},"stage":"planning","path":"/absolute/worktree","worktree":"/absolute/worktree","branch":"task/task-id","read_only":true,"checkpoint":null,"skills":[{"category":"development","filename":"development--one.md","content":"Instructions"}]}
```

`path` и `worktree` должны канонически указывать на один существующий каталог.
`checkpoint` — объект или null. Дополнительные поля: `plan_text`, `feedback`,
`result_data`; они передаются deepagents вместе с задачей и skills.
Skills читаются из `content` снимка stdin, без файлов `workflow/skills/`.
Категория берётся из `category`, иначе из префикса `filename`/`name`.

```json
{"type":"plan","plan_text":"Human-readable plan"}
{"type":"progress","message":"Saved","checkpoint":{"step":1}}
{"type":"test_result","command":"test -s runner-stub.txt","exit_code":0,"summary":"passed"}
{"type":"result","result_summary":"Implemented","result_data":{"changed_paths":["runner-stub.txt"]}}
{"type":"failure","message":"Skill verification failed","checkpoint":{"step":1}}
```

Одна строка до 1 МиБ, немедленный flush. Planning строго read-only и завершается
единственным `plan`. Другие этапы — одним `result`, exit 0. Ошибка даёт `failure`
с последним checkpoint, exit 1. Publication возвращает `result` с `success` и
`message`: ошибки команд означают `success:false`, exit 0.
Checkpoint продолжает входной объект, отражая завершённые действия/проверки.
Повтор stub безопасно записывает то же содержимое файла.

## Ветка, коммит и заявленные пути

- Runner работает в worktree задачи на ветке `task/<task_id>`, которую создал
  harness. Harness коммитов, `add`, `push` и `merge` не делает.
- Коммит делает runner на этапе publication: изменение фиксируется в ветке
  `task/<task_id>` до отчёта `result`, чтобы опубликованное состояние было
  воспроизводимым. Публикация запускается только после решения `publish`.
- `result_data.changed_paths` — **заявленные** пути. Runner перечисляет в нём
  файлы, которые, по его данным, изменил; сервер сохраняет список как есть и
  не сверяет его с `git diff`/`git status`. Это известное ограничение MVP.
- Ограничение реализации: собственного шага `git commit` в коде runner нет,
  git-команды берутся из skills этапа publication, а команды skills
  выполняются в изолированной копии worktree без `.git` (см. `safe_fs.py`,
  `sandbox_paths.py`). Для реального коммита нужен runner, который коммитит до
  отчёта, либо команда git вне такой копии. Сквозной прогон 12.1 использовал
  внешний stub-runner, который коммитил сам.

## Stub и команды skills

Stub даёт постоянный план, на implementation записывает `runner-stub.txt`
с фиксированным содержимым. На testing выполняет shell-блоки skills;
implementation команды не запускает. Несколько блоков исполняются последовательно,
один блок — одна команда; timeout 300 секунд.
Поддерживаются fences `sh`, `bash`, `python`, `python3` и без языка;
начальный `$ ` удаляется. Остальные языки явно отклоняются.
Пример skill категории `testing`:

````markdown
Проверь результат:
```sh
test -s runner-stub.txt
```
````

sh/пустой язык запускается через /bin/sh, bash через /bin/bash,
python/python3 через python3; остальные языки отклоняются. Команды работают
в bubblewrap: корень read-only, worktree — приватная копия, /tmp и /home отдельные
tmpfs, IPC и PID namespace изолированы, capabilities сброшены. Сеть закрыта
обязательным seccomp (socket/socketpair/io_uring), без `--unshare-net`, которому
нужен NETLINK_ROUTE; это поддерживает хосты с уже запрещёнными socket syscalls.
Нужен bwrap с `--bind-fd` (проверено на 0.11.1): mount-fd закрывается до команды.
Если bwrap недоступен, команда не запускается и runner сообщает sandbox_unavailable.
Системные файлы корня, например /etc/passwd, остаются читаемыми из read-only bind.
В копии и инструментах нет `.env*`, `.secrets`, `*.pem`, `*.key`, `id_rsa*`, `.npmrc`, `.pypirc`, `*.env`, `.git`, `.agent-token`.
Секретные каталоги исключаются целиком; hardlink, symlink и специальные файлы запрещены.
До публикации создаётся полная копия исходных видимых файлов; ошибка запускает восстановление.
Если оно не удалось, копия остаётся в `.env.runner-recovery-*` (0700), этап завершается failure.
Процесс запускается в новой сессии; таймаут завершает всю группу процессов.
Exit code и сводка отправляются через test_result; stdout/stderr отбрасываются.
Ошибка проверки завершает testing через failure. Без команд результат явно
сообщает `checks_run:0`; publication без команд возвращает `success:false`.
После publication runner коммитит разрешённые изменения вне sandbox.
Staging/проверка/commit используют приватный `GIT_INDEX_FILE`; реальный индекс не меняется.

## Deepagents

```bash
.venv/bin/pip install -e '.[deepagents]'
```

Явные переменные процесса имеют приоритет. Конфигурация один раз читает
AGENT_FLOW_RUNNER_ENV_FILE или $HOME/.config/agents-flow/runner.env.
Файл должен быть обычным и иметь права не шире 0600; допустимы строки
OPENAI_API_KEY=..., OPENAI_BASE_URL=..., AGENT_MODEL=....

| Переменная | Значение |
|---|---|
| AGENT_PROVIDER | stub по умолчанию; основной SDK — deepagents; адаптер — openai-compatible |
| `OPENAI_BASE_URL` | HTTP(S) endpoint, по умолчанию `https://api.openai.com/v1` |
| OPENAI_API_KEY | Ключ API можно хранить в runner.env; не помещать в YAML/аргументы |
| OPENAI_MODEL / AGENT_MODEL | Модель; OPENAI_MODEL приоритетнее. В runner.env поддерживается AGENT_MODEL |

Передайте ключ через менеджер секретов/окружение родительского процесса harness.
Проверка конфигурации без сети и вывода ключа:

```bash
.venv/bin/python -c 'from runner.config import Config; Config.from_env()'
```

deepagents создаёт агента через SDK и OpenAI-compatible chat model.
openai-compatible использует тонкий OpenAIAdapter с JSON response format,
таймаутом 60 секунд и без повторов. Endpoint должен поддерживать
response_format {type: json_object}. Агент выполняет до 40 файловых действий:
list/read/write/finish, читает skills,
approved plan, feedback и checkpoint. Произвольной shell-команды от модели нет.
Testing/publication используют skill-блоки без вызова модели.

Файловые инструменты используют открытые directory descriptors и O_NOFOLLOW
для каждого компонента пути; чтение и атомарная запись не перепроверяют затем
обычный путь. Защищённые компоненты сравниваются через casefold; hardlink запрещены.
Лимит файла — 256 КиБ; planning запрещает запись; другой st_dev даёт `mount_crossing`.
Окружение команд: только PATH, HOME, LANG, TZ, TERM; HOME — sandbox tmpfs.
API-ключи и harness-токены не наследуются командами; ошибки API и сырые ответы не логируются.
Снимок секретов создаётся при загрузке Config; ротация — явный `config.reload()`.
Очистка защищает subject, события, историю SDK, имена и артефакты; Git hooks/filters/GPG отключены.
Модельные пути распределяются до очистки с учётом исходного имени, существующих файлов
и коллизий каждого компонента; повторный путь внутри запуска сохраняет назначение.
Модель доверия, формы кодирования и ограничения MVP: [SECURITY.md](SECURITY.md).
