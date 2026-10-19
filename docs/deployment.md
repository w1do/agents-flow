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
   из конфига и парами `<workspace_id>=<clone_url>`. Скрипт идемпотентен: повторный запуск безопасен.
4. `harness-server sandbox pause` — песочница уходит в простой до первой задачи.

### Песочница в `error` с закреплённой задачей

`sandbox resume` отвечает «занята», если за песочницей закреплена задача. Владелец проверяет состояние
(`harness-server sandbox status`, событие задачи через `GET /tasks/{id}` с `HARNESS_ADMIN_TOKEN`), убеждается,
что агент в песочнице не работает, и затем вручную в БД сбрасывает `current_task_id` и статус песочницы.
Это разовое действие владельца, не команда CLI; SQL с конкретными значениями в документацию не добавляется.

## Песочница: токены, изоляция и allowlist (mvp-06)

- Токен подписки `CLAUDE_CODE_OAUTH_TOKEN` и `GITLAB_TOKEN` живут только в ENV Dokploy. Агент получает их
  в env одной команды запуска, в файлы песочницы они не пишутся (проверяется тестами и live-тестом).
- Ротация `CLAUDE_CODE_OAUTH_TOKEN` не реже 90 дней и сразу при подозрении на утечку (`claude setup-token`
  заново, затем обновить ENV и перезапустить worker).
- Рекомендуется отдельный аккаунт или подписка под харнесс: токен доступен процессу агента, а исходящий HTTPS открыт.
- Исходящий allowlist Novita (`network.allow_out`, IP/CIDR) рекомендуется ограничить адресами GitLab, Telegram,
  Anthropic и Novita. Код не применяет его в MVP: песочница создаётся вручную (D-38).
- Claude Code в песочнице запускается с `--setting-sources user` и `--strict-mcp-config`: hooks и MCP-серверы
  репозитория задачи не выполняются (D-36). Bootstrap не кладёт hooks и plugins в профиль песочницы.
