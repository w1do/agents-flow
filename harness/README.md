# harness

Go-бинарник подключения Git-проекта к Agents Flow. Реализованы пункты 8.1–8.8:
init, REST-клиент, skills, аренды, worktree и цикл внешнего runner.

## Сборка и команды

Linux, Go 1.24+, Git; зависимость — `gopkg.in/yaml.v3`.
Для runner нужны доступный `/proc` и разрешённый `PR_SET_CHILD_SUBREAPER`.
Запускать `run` нужно от непривилегированной учётной записи: supervisor
включает `PR_SET_NO_NEW_PRIVS` и не работает от `root`. На других ОС `run`
отклоняется до claim.

```bash
go mod tidy
go build -o /tmp/harness ./cmd/harness
cd /path/to/project
/tmp/harness init <project_id> --server-url https://flow.example.com --agent-name my-agent
/tmp/harness run
```

Перед `run` задайте внешний runner в `workflow/config.yaml`:

```yaml
runner:
  command: ["/absolute/path/to/runner", "--optional-argument"]
  timeout_seconds: 1800
  decision_timeout_seconds: 3600
```

Команда задаётся массивом аргументов; автоматического выбора runner нет.
Нулевые/отсутствующие таймауты означают 1800 и 3600 секунд соответственно.
Контракт входа и событий: [RUNNER.md](RUNNER.md).

URL также можно передать через `AGENTS_FLOW_SERVER_URL`. Init-код читается из
`AGENTS_FLOW_INIT_TOKEN` или stdin; аргумента командной строки для секрета нет.

`init` работает из любого подкаталога Git-проекта, читает URL `origin` и отправляет
его как `git_remote`; в локальном конфиге `git_remote: origin` — имя remote.
Репозиторий без origin допускается: необязательный URL не передаётся.
Существующий `workflow/` не перезаписывается. До успешного ответа сервера
каталог не создаётся; при ошибке записи незавершённый каталог удаляется.

Создаётся только `workflow/{config.yaml,.gitignore,.agent-token,skills/}`.
Токен хранится в `.agent-token` с правами 0600, игнорируется Git и не входит в YAML.
Клиент не включает тела ошибок в диагностику и не следует HTTP-редиректам.
Адрес сервера обязан быть HTTPS; `http` допустим только для loopback или при
явном `allow_insecure` (`--allow-insecure` у `init`, ключ `allow_insecure`
в YAML для `run`).

## Пакеты

| Пакет | Назначение |
|---|---|
| `cmd/harness`, `internal/cli` | Разбор `init`, `run`, справка |
| `internal/bootstrap`, `internal/gitrepo` | Init и чтение Git-метаданных |
| `internal/config` | Строгий YAML и отдельный токен |
| `internal/api` | Контракты REST, Bearer, повторы и идемпотентность |
| `internal/skills` | Полный набор файлов, защита активной задачи |
| `internal/leases` | Один claim, состояние аренды и отдельный heartbeat |
| `internal/workspace` | Создание и повторное использование worktree |
| `internal/agent` | Цикл run, runner-процесс, checkpoint и журнал отчёта |
| `internal/atomicfs` | Запись через `os.Root` и атомарная подмена файла |
| `internal/jsonx` | Строгий JSON с `UseNumber` на всех границах |
| `internal/procguard` | Supervisor процесса runner (Linux subreaper) |
| `internal/testutil` | Временные Git-репозитории для тестов |

API повторяет ошибки транспорта, таймауты и 5xx (по умолчанию три попытки,
backoff 200/400 мс, таймаут попытки 10 с). 4xx возвращаются сразу.
Изменяющий запрос получает один `Idempotency-Key` на все попытки; при возобновлении
запроса можно передать сохранённый ключ в `Client.Request`.
Claim отправляет `{}`, idle heartbeat — два null, активный — task_id и lease_id.

`Manager.Claim` делает немедленную попытку и возвращает nil при 204.
Повторный/параллельный claim занятого агента блокируется локально; серверный 409
тоже означает «занят». После неоднозначной ошибки claim сохраняет ключ повтора.
`StartHeartbeat` сразу возвращает канал ошибок и работает до отмены контекста.
Потеря связи сохраняет состояние; 409 активного heartbeat помечает lease потерянным,
останавливает heartbeat и требует прекращения работы. `Release` вызывается явно.

`run` синхронизирует skills только между задачами и ждёт poll_interval после 204.
На всю задачу запускается heartbeat с интервалом TTL/3. Планирование → решение
по плану → реализация → проверки → результат → решение по результату → публикация.
До `publish` runner не получает skills категорий с префиксами git/deploy.
`rework` повторяет реализацию и проверки, передавая feedback. `keep_ready` оставляет
задачу в ready, продолжая heartbeat и ожидание последующего решения.
Отклонение плана возвращает planning с feedback; trash и остановленные статусы
прекращают текущий запуск без fail.

Ожидание решения ограничено decision_timeout_seconds: по истечении `run` выходит,
сохраняя задачу. SIGINT/SIGTERM останавливают heartbeat, runner и его дочерние
процессы; worktree остаётся для возобновления. Runner stderr не выводится.
Ненулевой exit, событие failure и некорректный NDJSON вызывают fail с сохранением
последнего checkpoint. Сетевые ошибки повторяются, сами по себе задачу не завершают.
Сбои публикации отправляются через publication-result с success=false.

JSON-журнал одного агента находится в `<git-dir>/agents-flow-harness/state.json`,
блокировка — в соседнем run.lock; рабочая копия не получает служебных файлов.
Journal — компактный индекс. Полные claim и runtime-state, включая pending,
хранятся отдельно в `snapshots/<sha256>.json` с правами 0600; контрольная сумма
проверяется при загрузке. Запись не обрезает и не меняет вход задачи; секреты
маскируются в сохраняемой копии. После атомарной фиксации удаляются старые snapshots.
При перезапуске восстанавливается аренда и повторяется тот же pending-запрос.
409 останавливает работу без fail. Для heartbeat `Task is finished` во время
подтверждения финального отчёта разрешён только повтор этого отчёта с прежним ключом;
409 самого отчёта по-прежнему означает потерю аренды.

`workspace.Ensure` создаёт соседний каталог `<repo>-task-<полный task_id>`
от HEAD на ветке `task/<task_id>`. Зарегистрированная ветка переиспользуется
вместе с незакоммиченными изменениями, в том числе при нестандартном пути.
Основная копия не переключается. Совпадение пути с чужим каталогом — ошибка.
Путь записывается в checkpoint; при восстановлении проверяется реестр Git worktree.

## Проверки

```bash
gofmt -l .
go vet ./...
go build ./...
go test ./...
go test -race ./...
```

Тесты используют `httptest` на loopback и временные Git-репозитории, без внешних
сервисов. Проверяются повторы API, init/права/игнорирование токена, skills,
конкурентный claim, heartbeat и неизменность основной копии после worktree.
Сквозные тесты запускают настоящий helper-процесс runner, покрывают publish/rework,
отказ/корзину, ready, 409, ошибки runner, повтор отчёта, восстановление и сигналы.

Документация: [../docs/harness.md](../docs/harness.md).
