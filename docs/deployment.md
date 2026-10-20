# Деплой (Dokploy + GitLab CI)

## Стеки

| Стек | Файл | Сервисы | Заметки |
|---|---|---|---|
| БД | `deploy/db/docker-compose.yml` | `postgres` | Отдельный Compose-сервис Dokploy, volume, без `ports` |
| Харнесс | `docker-compose.yml` | `migrate` → `server`, `worker`; `console` после MVP | Один образ для migrate/server/worker |

- Все сервисы в внешней сети `dokploy-network`; наружу только `expose`.
- Домен и HTTPS — в Dokploy на `server` (и `console` позже). Песочницам Novita нужен публичный HTTPS `/mcp` (A2).
- `migrate` — одноразовый (`alembic upgrade head`); `server` и `worker` стартуют через
  `depends_on: { migrate: { condition: service_completed_successfully } }`.
- Секреты приложения — только в Environment Dokploy. `config/harness.yaml` — File Mount Dokploy.

## Первый деплой в Dokploy (без реестра)

Реестра GitLab пока нет: CI не запускался, remote репозитория — GitHub (D-59). Dokploy собирает образ сам
из `Dockerfile` по `docker-compose.yml`, поэтому `HARNESS_IMAGE` не задаётся. Раздел «CI» ниже — цель после переноса в GitLab.

1. **Postgres.** Нативный сервис Dokploy `postgres:16` в той же сети `dokploy-network`, порты наружу не публикуются.
   `DATABASE_URL` стека харнесса указывает на внутренний хост этого сервиса (имя сервиса в Dokploy), пользователь,
   пароль и база — из его настроек. Пароль в документацию и репозиторий не пишется.
2. **Стек харнесса.** Dokploy → Compose → Source: GitHub `w1do/agents-flow`, ветка `main`, Compose Path `docker-compose.yml`.
   Dokploy выполняет `build` из `Dockerfile`; образ получает локальный тег `agents-flow:local`, один на migrate, server и worker.
3. **Домен.** Домен `flow.w1do.ru` привязать к сервису `server`, порт `8000`, HTTPS: Let's Encrypt.
   `HARNESS_PUBLIC_URL=https://flow.w1do.ru`.
4. **File Mount.** Файл `harness.yaml` с боевыми значениями (ссылки `vault:…`, workspace, sandbox) — путь монтирования
   `config/harness.yaml`. Образец — `config/harness.example.yaml`; боевой файл в репозиторий не коммитится.
5. **ENV.** Environment стека в Dokploy: обязательные и опциональные переменные из ARCHITECTURE.md §9, которые нужны
   текущим этапам. Значения секретов — только в Dokploy. `docker-compose.yml` передаёт все переменные из `Settings`;
   тест `apps/server/tests/test_compose.py` следит за этим.
6. **Запуск.** Сначала выполняется `migrate` (`alembic upgrade head`), затем стартуют `server` и `worker`.
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
File Mount → Deploy (так выкачен D-60). После деплоя: `https://flow.w1do.ru/health` и, если менялась песочница,
`harness-server sandbox bootstrap` в терминале контейнера `server` или `worker`. Ключ Dokploy в документацию и
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
3. Создать песочницу в Novita вручную, записать id в `harness.yaml` (`sandbox.provider_id`), затем выполнить
   `harness-server sandbox bootstrap`: команда загружает `deploy/sandbox/bootstrap.sh` и запускает его с версиями
   из конфига и парами `<workspace_id>=<clone_url>`. Bootstrap идёт в три шага: `--phase setup` без ключей, затем
   клоны и fetch делает сервер отдельной git-командой на каждый workspace с ключом только этого workspace, затем
   `--phase memory` с индексацией памяти (только с `EMBEDDING_API_KEY`). Workspace без ключа клонируется анонимно (D-62).
   Скрипт идемпотентен: повторный запуск безопасен. Команда запускается в терминале Dokploy контейнера `server` или `worker` (из любого каталога): `harness-server sandbox bootstrap`; скрипт лежит в образе — `/app/deploy/sandbox/bootstrap.sh`, другой путь — `--script <путь>` (D-63).
4. `harness-server sandbox pause` — песочница уходит в простой до первой задачи.

### Песочница в `error` с закреплённой задачей

`sandbox resume` отвечает «занята», если за песочницей закреплена задача. Владелец проверяет состояние
(`harness-server sandbox status`, событие задачи через `GET /tasks/{id}` с `HARNESS_ADMIN_TOKEN`), убеждается,
что агент в песочнице не работает, и затем вручную в БД сбрасывает `current_task_id` и статус песочницы.
Это разовое действие владельца, не команда CLI; SQL с конкретными значениями в документацию не добавляется.

## Песочница: профиль и память (sandbox-profile)

- Ключи владельца лежат в vault. Серверу нужны ENV `VAULT_MCP_URL` (только `https://`) и `VAULT_MCP_TOKEN` (секрет).
  В `harness.yaml` — ссылки `workspaces[].repo.access_ref` (ключ записи репозитория workspace) и
  `sandbox.memory.embedding_ref` вида `vault:<project>/<service>/<name>`. ENV `GITLAB_TOKEN`/`GITLAB_URL`
  больше не читаются (D-60). Workspace без `repo.access_ref` клонируется анонимно, а его задачи уходят в `error`.
- Значения для боевого запуска (D-50): `VAULT_MCP_URL=https://safe.w1do.ru/mcp`; `VAULT_MCP_TOKEN` — значение задаёт
  владелец и вносит только в ENV Dokploy (в репозиторий и документацию не пишется). В боевом `harness.yaml`:
  `repo.access_ref: "vault:Repository/Gitlab/админский"` (GitLab-workspace), `repo.access_ref: "vault:Repository/Github/админский"`
  (`w1do/chistotyumen`) и `sandbox.memory.embedding_ref: "vault:Сервисы/Polza/EmbeddingsMemory"`.
  В `config/harness.example.yaml` эти ссылки не заносятся.
- Первый bootstrap с памятью (после заполнения `sandbox.memory`): `harness-server sandbox bootstrap`. Команда
  ставит Node 22, Docker, memory-agent из GitHub на коммите `sandbox.memory.ref` и индексирует клоны. Повторный запуск не
  переустанавливает совпадающие версии и не клонирует заново.
- Блок памяти в `harness.yaml` (закреплённый коммит memory-agent, D-51):
  ```yaml
  sandbox:
    memory:
      ref: 09e5e63ac721db75020fcfa69e33930750975139
      embedding_ref: vault:Сервисы/Polza/EmbeddingsMemory
  ```
  `repo` не задан — `w1do/memory-agent`. Пакет `project-memory` из реестра npm не ставится: он чужой.
- memory-agent собирается от пользователя песочницы по lockfile коммита; команда `memory` — симлинк `/usr/local/bin/memory`.
- Обновление memory-agent: новый полный sha в `ref` и повторный `harness-server sandbox bootstrap`. Тег и ветка
  в `ref` не принимаются; маркер `~/.harness/memory/installed-ref` сверяет установленный коммит.
- Рекомендация: ключ embeddings для песочницы — отдельный ключ Polza с лимитом расходов, не основной ключ.
  Ключ доступен процессам песочницы на время команды (см. design, Risks).
- После паузы Novita демон Docker поднимает `~/.harness/bin/ensure-docker.sh`; активация вызывает его сама.
- Ошибка vault при bootstrap: код 1, причина `vault`, строка песочницы не меняется. Ошибка vault при активации:
  задача в `error` с причиной `vault`. Сбой `memory sync` при активации задачу не роняет (см. лог worker).

## Песочница: токены, изоляция и allowlist (mvp-06)

- Токен подписки `CLAUDE_CODE_OAUTH_TOKEN` живёт только в ENV Dokploy, ключи репозиториев — в vault. Агент получает их
  в env одной команды запуска, в файлы песочницы они не пишутся (проверяется тестами и live-тестом).
- Ротация `CLAUDE_CODE_OAUTH_TOKEN` не реже 90 дней и сразу при подозрении на утечку (`claude setup-token`
  заново, затем обновить ENV и перезапустить worker).
- Рекомендуется отдельный аккаунт или подписка под харнесс: токен доступен процессу агента, а исходящий HTTPS открыт.
- Исходящий allowlist Novita (`network.allow_out`, IP/CIDR) рекомендуется ограничить адресами GitLab, Telegram,
  Anthropic и Novita. Код не применяет его в MVP: песочница создаётся вручную (D-38).
- Claude Code в песочнице запускается с `--setting-sources user` и `--strict-mcp-config`: hooks и MCP-серверы
  репозитория задачи не выполняются (D-36). Bootstrap не кладёт hooks и plugins в профиль песочницы.

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
4. Подготовленная песочница: повторный `harness-server sandbox bootstrap` делает `set-url origin` и fetch с
   новым заголовком. Клоны публичных репозиториев не меняются.

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
