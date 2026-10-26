# Деплой (Dokploy + GitLab CI)

## Переход на локальную машину агента

Это руководство описывает ручную процедуру; ничего здесь автоматически не устанавливается и не выполняется. Выполняет оператор. Изменение `local-agent-machine` ещё не принято целиком: runtime-пункты 3–5 заблокированы до успешного повторного теста `4.5`; не проводить производственный rollout до снятия этого блокера и приёмки.

1. **Подготовить хост.** Установить и проверить `git`, Node.js не ниже 22.13, `npm`, клиент Claude (`claude`) и `openspec`. Если включена память проекта, дополнительно нужны `memory` и Docker Compose. Оператор отвечает за установку/версии; агент сам инструменты не устанавливает.
2. **Обновить конфигурацию проекта.** В операторской копии `harness.yaml` применить актуальную форму из `config/harness.example.yaml`: локальный `sandbox.provider_id`, удалить устаревшие поля версий CLI и поля `sandbox.memory.repo`/`ref`, сохранив актуальный `embedding_ref`, если память настроена. Проверить конфигурацию до выката; боевой файл не коммитить.
3. **Инициализировать проект.** Для каждого проекта выполнить `agent init <project>` от непривилегированного пользователя, после установки prerequisites и доступов. Проверить результат и маркеры инициализации перед назначением задач.
4. **Worker на хосте.** Установить и настроить user unit по [`deploy/worker/README.md`](../deploy/worker/README.md), проверить его конфигурацию и запуск по инструкции оператора. Worker работает на хосте, не в Compose. Остановка unit сама по себе не останавливает уже запущенные процессы агентов: сначала прекратить новые назначения, затем дождаться завершения или явно отменить активные задания и убедиться, что процессы завершились.
5. **Compose и Dokploy.** Использовать актуальный Compose без сервиса worker. Удалить устаревшие переменные `NOVITA_*` из Environment Dokploy после проверки их отсутствия в актуальной конфигурации; не помещать секреты в файлы или команды.
6. **Удалить старую запись sandbox из БД (вручную, только оператором).** Сначала сделать проверенный бэкап БД. Прекратить новые назначения, дренировать очередь и дождаться завершения/отмены активных заданий; перед остановкой worker удостовериться, что агентские процессы завершились. Убедиться по фактической production-схеме и ограничениям, что таблица/поля и условия ниже применимы. Ожидаемые поля `sandboxes`: `id` UUID, `provider_id` unique, `status`, nullable `current_task_id`, `agent_pid`, `agent_started_at`; допустимые статусы включают `paused`, `active`, `error`. Не полагаться на это описание вместо проверки живой схемы.

   Оператор обязан подставить точные старые UUID и `provider_id`, а также текущий `sandbox.provider_id` из конфигурации. Не предполагать значение `local`. Выполнять в доверенной SQL-консоли/сессии с безопасной аутентификацией; не передавать пароль или секретный URL подключения в argv. Использовать типизированные/кавыченные параметры клиента либо явно заменить безопасные плейсхолдеры точными значениями.

   ```sql
   BEGIN;
   SELECT id, provider_id, status, current_task_id, agent_pid, agent_started_at
   FROM sandboxes
   WHERE id = :'OLD_SANDBOX_UUID'::uuid
     AND provider_id = :'OLD_PROVIDER_ID'
   FOR UPDATE;
   ```

   Продолжать только если SELECT вернул ровно выбранную оператором запись и все три поля активности равны `NULL`. Затем выполнить условное удаление:

   ```sql
   DELETE FROM sandboxes
   WHERE id = :'OLD_SANDBOX_UUID'::uuid
     AND provider_id = :'OLD_PROVIDER_ID'
     AND provider_id <> :'CURRENT_CONFIGURED_PROVIDER_ID'
     AND status = 'paused'
     AND current_task_id IS NULL
     AND agent_pid IS NULL
     AND agent_started_at IS NULL
   RETURNING id, provider_id;
   ```

   Удаление допустимо только если `RETURNING` показал ровно одну ожидаемую запись. Ноль строк, несколько/неожиданная строка, активность, несовпадение схемы или любая ошибка — немедленно `ROLLBACK`, выяснить причину; не обходить ограничения. Не использовать `CASCADE`, отключение FK, широкие DELETE или принудительное обнуление активности. Только после проверки оператором ровно одной ожидаемой удалённой записи выполнить отдельной командой `COMMIT`; иначе `ROLLBACK`. Не объединять COMMIT безусловно с copy/paste-блоком.

Эти шаги и SQL не исполнялись в рамках подготовки документации. Установка, конфигурация, миграция данных, удаление ENV и живая проверка остаются ответственностью владельца.

## Стеки

| Стек | Файл | Сервисы | Заметки |
|---|---|---|---|
| БД | `deploy/db/docker-compose.yml` | `postgres` | Отдельный Compose-сервис, volume; порт только на `127.0.0.1:5432` хоста |
| Харнесс | `docker-compose.yml` | `migrate` → `server`; `console` после MVP | Образ migrate/server; worker запускается на хосте systemd user unit |

- Все сервисы в внешней сети `dokploy-network`; наружу только `expose`.
- Домен и HTTPS — в Dokploy на `server` (и `console` позже). Агенту на машине агента нужен публичный HTTPS `/mcp` (адрес `HARNESS_PUBLIC_URL` + `/mcp`, A2, D-38).
- `migrate` — одноразовый (`alembic upgrade head`); `server` стартует после успешного `migrate`. Worker не входит в Compose.
- Секреты приложения — только в Environment Dokploy. `config/harness.yaml` — File Mount Dokploy.

## Первый деплой в Dokploy (без реестра)

Реестра GitLab пока нет: CI не запускался, remote репозитория — GitHub (D-59). Dokploy собирает образ сам
из `Dockerfile` по `docker-compose.yml`, поэтому `HARNESS_IMAGE` не задаётся. Раздел «CI» ниже — цель после переноса в GitLab.

1. **Postgres.** Разверните `deploy/db/docker-compose.yml`: volume сохраняет данные, порт опубликован только на loopback `127.0.0.1:5432`, сервис подключён к `dokploy-network`. `DATABASE_URL` контейнера server указывает на DB в общей Docker-сети; host worker использует `127.0.0.1:5432`. Пользователь,
   пароль и база — из его настроек. Пароль в документацию и репозиторий не пишется.
2. **Стек харнесса.** Dokploy → Compose → Source: GitHub `w1do/agents-flow`, ветка `main`, Compose Path `docker-compose.yml`.
   Dokploy выполняет `build` из `Dockerfile`; образ получает локальный тег `agents-flow:local`, общий для migrate и server.
3. **Домен.** Домен `flow.w1do.ru` привязать к сервису `server`, порт `8000`, HTTPS: Let's Encrypt.
   `HARNESS_PUBLIC_URL=https://flow.w1do.ru`.
4. **File Mount.** Файл `harness.yaml` с боевыми значениями (ссылки `vault:…`, workspace, sandbox) — путь монтирования
   `config/harness.yaml`. Образец — `config/harness.example.yaml`; боевой файл в репозиторий не коммитится.
5. **ENV.** Environment стека в Dokploy: обязательные и опциональные переменные из ARCHITECTURE.md §9, которые нужны
   текущим этапам. Значения секретов — только в Dokploy. `docker-compose.yml` передаёт все переменные из `Settings`;
   тест `apps/server/tests/test_compose.py` следит за этим.
6. **Запуск.** Сначала выполняется `migrate` (`alembic upgrade head`), затем стартует `server`. Worker отдельно устанавливается оператором как systemd user service; см. [`deploy/worker/README.md`](../deploy/worker/README.md). Это описание артефакта, не подтверждение установки или живой приёмки.
7. **Webhook Telegram.** В терминале контейнера `server` (Dokploy → сервис server → Terminal):
   `harness-server telegram set-webhook`. Команда регистрирует `https://flow.w1do.ru/telegram/webhook` с секретом
   `TELEGRAM_WEBHOOK_SECRET`. Повторять при смене домена или секрета.
8. **Проверка.** `https://flow.w1do.ru/health` отвечает успехом; healthcheck сервиса `server` использует тот же путь.

Сборка без реестра: образ каждый раз пересобирается при деплое из текущего `main`. Когда появится реестр GitLab (CI),
`build` в Compose и `HARNESS_IMAGE` переводятся на `registry.gitlab.com/…:main` (см. раздел «CI»).

### Выкат обновлений

Панель Dokploy — `https://deploy.w1do.ru`, проект `agents-flow`, Compose `harness`. Автодеплой на push в `main`
выключен: слияние PR прод не меняет, выкат — только кнопкой Deploy или API (`POST /api/compose.deploy` с
`composeId` стека, заголовок `x-api-key` — ключ из vault `Deploy/Dokploy/prod`; File Mount правится через
`POST /api/mounts.update`). Поэтому изменение, ломающее `harness.yaml`, выкатывается так: слить PR → поправить
File Mount → Deploy (так выкачен D-60). После деплоя: `https://flow.w1do.ru/health` и, если менялась машина агента, `agent init <project>` на хосте (D-64).
Ключ Dokploy в документацию и
репозиторий не пишется.

## CI (`.gitlab-ci.yml`)

```
check:python    (MR и main): uv sync --frozen, ruff check, ruff format --check, mypy, pytest;
                             Postgres — сервис postgres:16-alpine, TEST_DATABASE_URL задан в job
check:openspec  (MR и main): openspec validate --all
build:image     (main):      buildx build --push, cache из registry (:buildcache)
                             → :$CI_COMMIT_SHORT_SHA и :main
deploy:dokploy  (main):      curl -fsS -X POST "$DOKPLOY_WEBHOOK_URL"
```

В переменных GitLab только `DOKPLOY_WEBHOOK_URL` и встроенные `CI_REGISTRY_*`. Цель — push → выкат до 10 минут.

`DOKPLOY_WEBHOOK_URL` задаётся в GitLab как **masked** и **protected**: URL содержит токен вызова Dokploy.
Job `deploy:dokploy` не добавляет `curl -v` и `--trace`: при ошибке curl может напечатать URL в вывод job,
а masked-переменная скрывает значение только в выводе, где GitLab его распознаёт.

`alembic check` в CI пока не запускается: без моделей `target_metadata` пустой, и команда падает.
Шаг добавляется в `check:python` вместе с моделями (mvp-03).

Известное ограничение: пайплайн GitLab на реальном MR не запускался — remote репозитория GitHub.
Проверены структура YAML и команды job `check:python` локально. Пайплайн нужно проверить при первом MR в GitLab
(`check:python`, `check:openspec`, `build:image`, `deploy:dokploy`).

## Первый запуск

1. Задеплоить стек БД, затем стек харнесса с ENV из ARCHITECTURE.md §9.
2. `harness-server telegram set-webhook` — регистрирует `${HARNESS_PUBLIC_URL}/telegram/webhook` с секретом
   `TELEGRAM_WEBHOOK_SECRET`. Запускается в контейнере `server` после деплоя и при каждой смене `HARNESS_PUBLIC_URL`
   или секрета. `HARNESS_PUBLIC_URL` должен быть https без учётных данных, иначе команда завершится с кодом 1 и
   понятным сообщением. Вывод команды токен и секрет не содержат.
3. Подготовить машину агента по разделу «Переход на локальную машину агента» (шаги 1–3) и выполнить
   `agent init <project>` от непривилегированного пользователя для каждого проекта. `sandbox.provider_id` в
   `harness.yaml` задаёт id, который проверяет `LocalSandboxProvider` (D-64). Процедура повторного запуска
   `agent init` не принята (TODO: задача 4.5 `local-agent-machine`).
4. Worker запускать на хосте как systemd user unit по инструкции [`deploy/worker/README.md`](../deploy/worker/README.md);
   остановка unit не завершает процессы агента автоматически.

### Задача осталась закреплена за машиной

Если задача осталась закреплена, сначала проверьте её через `GET /tasks/{id}` и убедитесь на хосте, что процесс
агента завершился. Не очищайте `current_task_id` вручную, пока не установлены причина сбоя и состояние процесса;
процедура восстановления для такого сбоя не подтверждена: TODO описать после приёмки runtime-пунктов 3–5
`local-agent-machine`.

## Настройки профиля и память агента (sandbox-profile)

- Ключи владельца лежат в vault. Серверу нужны ENV `VAULT_MCP_URL` (только `https://`) и `VAULT_MCP_TOKEN` (секрет).
  В `harness.yaml` — ссылки `workspaces[].repo.access_ref` (ключ записи репозитория workspace) и
  `sandbox.memory.embedding_ref` вида `vault:<project>/<service>/<name>`. ENV `GITLAB_TOKEN`/`GITLAB_URL`
  больше не читаются (D-60). Workspace без `repo.access_ref` клонируется анонимно, а его задачи уходят в `error`.
- Значения для боевого запуска (D-50): `VAULT_MCP_URL=https://safe.w1do.ru/mcp`; `VAULT_MCP_TOKEN` — значение задаёт
  владелец и вносит только в ENV Dokploy (в репозиторий и документацию не пишется). В боевом `harness.yaml`:
  `repo.access_ref: "vault:Repository/Gitlab/админский"` (GitLab-workspace), `repo.access_ref: "vault:Repository/Github/админский"`
  (`w1do/chistotyumen`) и `sandbox.memory.embedding_ref: "vault:Сервисы/Polza/EmbeddingsMemory"`.
  В `config/harness.example.yaml` эти ссылки не заносятся.
- Память (после заполнения `sandbox.memory.embedding_ref`): `agent init <project>` на машине агента выполняет
  `memory init` с ключом embeddings только в env команды (задача 4.4 `local-agent-machine`). Инструменты `memory` и
  Docker Compose ставит оператор, `agent init` их проверяет (задача 4.1).
- Блок памяти в `harness.yaml` (поля `repo` и `ref` сняты, D-64):
  ```yaml
  sandbox:
    memory:
      embedding_ref: vault:Сервисы/Polza/EmbeddingsMemory
  ```
  Пакет `project-memory` из реестра npm не ставится: он чужой (D-51).
- Как оператор ставит memory-agent на машину агента и как обновляет его версию, в документе не описано: TODO,
  процедура не подтверждена по коду. Проверка наличия команды `memory` — задача 4.1 `local-agent-machine`.
- Рекомендация: ключ embeddings для песочницы — отдельный ключ Polza с лимитом расходов, не основной ключ.
  Ключ доступен процессам песочницы на время команды (см. design, Risks).
- Скрипт `ensure-docker.sh` больше не вызывается (задача 5.2): демон Docker на машине агента поддерживает оператор (D-64).
- Ошибка vault при `agent init`: код 1, причина `vault` (задача 4.5, ещё не принята). Ошибка vault при активации:
  задача в `error` с причиной `vault`. Сбой `memory sync` при активации задачу не роняет (см. лог worker).

## Машина агента: токены и границы безопасности (D-64)

- Токен подписки `CLAUDE_CODE_OAUTH_TOKEN` задаётся в окружении worker; ключи репозиториев — в vault. Секреты
  передаются только явно указанным командам и не входят в очищенное окружение подпроцессов (D-64).
- Ротация `CLAUDE_CODE_OAUTH_TOKEN` не реже 90 дней и сразу при подозрении на утечку (`claude setup-token`
  заново, затем обновить ENV и перезапустить worker).
- Рекомендуется отдельный аккаунт или подписка под харнесс: токен доступен процессу агента, а исходящий HTTPS открыт.
- Код не ограничивает исходящий трафик машины агента. Ограничение сети — на стороне оператора; сетевые правила
  конкретного хоста не подтверждены: TODO (D-64, D-38).
- Claude Code запускается с `--setting-sources user` и `--strict-mcp-config`: hooks и MCP-серверы
  репозитория задачи не выполняются (D-36). Hooks и plugins в профиль пользователя не кладутся (D-48).

## Переход на D-60 (провайдер репозитория, git-providers)

Старая форма конфига не загружается: секция `gitlab:` и поле `workspaces[].gitlab_project` отклоняются с
сообщением, куда перенести поля. ENV `GITLAB_URL` и `GITLAB_TOKEN` сервер больше не читает. Порядок выката:

1. Правка боевого `harness.yaml` (один файл, до выката образа). Адрес GitLab переходит в `repo.base_url` workspace
   (можно не указывать: по умолчанию `https://gitlab.com`), `gitlab_project` — в `repo.project`, `gitlab.access_ref` — в
   `repo.access_ref`. Секцию `gitlab:` удалить:

   ```yaml
   workspaces:
     - id: demo
       name: Демо-проект
       voice_aliases: ["демо"]
       repo:
         provider: gitlab
         project: group/demo
         access_ref: "vault:Repository/Gitlab/админский"
     - id: chistotyumen
       name: Чистотюмень
       voice_aliases: ["чистотюмень"]
       repo:
         provider: github
         project: w1do/chistotyumen
         access_ref: "vault:Repository/Github/админский"
   ```

   Пока у workspace общий главный ключ владельца, fine-grained токен на репозиторий (Contents RW, Pull requests RW)
   — позже, отдельным шагом в vault (D-60). Ключ GitHub не пишется в файлы и документацию, только ссылка.
2. Удалить `GITLAB_TOKEN` и `GITLAB_URL` из ENV Dokploy: они не читаются, но остаются в настройках.
3. Выкатить образ. Если правка п. 1 не сделана, сервер не стартует и называет поле, которое надо перенести.
4. Процедура миграции существующих клонов не описана: TODO подтвердить по `agent init` и рабочей копии хоста до выката.

Откат: вернуть прежний образ и `harness.yaml` с секцией `gitlab:` (сохранить копию до правки).

## Telegram за прокси (сервер в РФ)

Сервер в РФ не достаёт `api.telegram.org`, поэтому трафик Telegram идёт через Cloudflare Worker владельца.
Код Worker живёт вне репозитория, в аккаунте Cloudflare владельца. Он обслуживает два маршрута:

- `/tg-webhook` — входящие апдейты: Telegram → Worker → `HARNESS_PUBLIC_URL/telegram/webhook`
  (Worker пересылает POST вместе с заголовком `X-Telegram-Bot-Api-Secret-Token`);
- `/bot<token>/<method>` и `/file/bot<token>/<path>` — исходящие вызовы Bot API и скачивание файлов:
  сервер → Worker → `api.telegram.org`.

Настройки сервера:

- `TELEGRAM_API_URL=https://<worker>` — базовый адрес исходящих вызовов;
- `TELEGRAM_WEBHOOK_URL=https://<worker>/tg-webhook` — адрес, который регистрирует `harness-server telegram set-webhook`.
  Без него адрес собирается из `HARNESS_PUBLIC_URL`.

Оба адреса: только `https://` строчными буквами, без пробелов, учётных данных, query и fragment.

Безопасность: прокси видит токен бота в пути URL. Используйте только свой Worker. Не включайте в нём
логирование URL и тел запросов. Секрет webhook проверяет сервер, а не Worker.
