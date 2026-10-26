# Работа с харнессом без веб-панели (UI)

Пошаговая инструкция: локальный запуск сервера и worker, приём задач через Telegram и проверка через CLI.
Веб-консоль (`apps/console`) для этого не нужна.

## Что работает без UI после mvp-06

- Текст и голос в Telegram принимаются, классифицируются через Polza (`work`, `status`, `unknown`).
- Для `work` бот присылает карточку задачи с кнопками проектов; нажатие кнопки переводит задачу в статус `planning`.
- На запрос о состоянии («что сейчас в работе») бот отвечает списком открытых задач из БД.
- Проект на машине агента подготавливается командой `agent init <project>` (D-64). В проде worker работает на этой машине как systemd user unit; в Compose worker нет. См. [deployment.md](deployment.md).
- Live-тесты запускаются вручную для Polza, Telegram и пути агента. Состав live-тестов меняется задачей 5.6 `local-agent-machine`.

Планировщик и исполнитель (код, MR) появятся в mvp-08 и mvp-09. До них задача после выбора проекта
остаётся в статусе `planning`.

## 1. Подготовка (один раз)

```bash
uv sync                                   # зависимости workspace
cp .env.example .env                      # секреты вписываются только в .env
cp config/harness.example.yaml config/harness.yaml
```

`.env` не коммитится. `.env.example` — шаблон в git, в него значения не вписываются.
Переменные читаются приложением из окружения, а не из файла, поэтому перед командами из этого документа
загружайте `.env` в текущую оболочку:

```bash
set -a; . ./.env; set +a
```

Обязательные переменные в `.env`:

| Переменная | Что задаёт |
|---|---|
| `DATABASE_URL` | Строка подключения к Postgres (пароль совпадает с контейнером из шага 3) |
| `HARNESS_CONFIG` | Путь к `config/harness.yaml` |
| `HARNESS_SECRET_KEY` | Ключ приложения; сгенерировать: `openssl rand -hex 32` |
| `TELEGRAM_BOT_TOKEN` | Токен бота от BotFather |
| `TELEGRAM_CHAT_ID` | Id чата владельца; без него сервер не стартует |
| `TELEGRAM_WEBHOOK_SECRET` | Секрет webhook, Telegram присылает его в заголовке |
| `POLZA_AI_KEY`, `POLZA_AI_MODEL` | Маршрутизатор. Модель выбирает владелец, в коде её нет |
| `CLAUDE_CODE_OAUTH_TOKEN` | Токен подписки Claude для агента: `claude setup-token` |
| `HARNESS_ADMIN_TOKEN` | Доступ к `GET /tasks/{id}`; не короче 32 символов без пробелов по краям |
| `HARNESS_PUBLIC_URL` | Публичный https-адрес сервера (туннель, см. шаг 4) |

Опциональные `STT_*` нужны для распознавания голоса. Без них голосовые сообщения получают ответ
«не удалось распознать, пришлите текстом».

### Как узнать `TELEGRAM_CHAT_ID`

1. Напишите боту из своего аккаунта любое сообщение.
2. Пока webhook не установлен, запросите обновления:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates"
```

3. В ответе найдите поле `message.chat.id` и впишите его в `.env`. Ответ содержит личные данные,
   не вставляйте его в чаты, документы и коммиты.

### Машина агента и проект

В `config/harness.yaml` укажите `sandbox.provider_id` — его проверяет `LocalSandboxProvider` (D-64). Для подготовки каждого проекта выполните `agent init <project>` от пользователя worker. Команде нужны `HARNESS_CONFIG`, `VAULT_MCP_URL`, `VAULT_MCP_TOKEN` и `HARNESS_PUBLIC_URL`; `DATABASE_URL` и переменные Telegram ей не нужны. Подробности — в [development.md](development.md) и [apps/server/README.md](../apps/server/README.md).

### Файл `.env.live` для live-тестов

Файл `.env.live` тоже не коммитится. Он ссылается на переменные из `.env` и добавляет параметры live-тестов:

```bash
LIVE_POLZA_API_KEY=${POLZA_AI_KEY}
LIVE_POLZA_MODEL=${POLZA_AI_MODEL}
LIVE_TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
LIVE_TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
LIVE_CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}
```

Загрузка для live-тестов:

```bash
set -a; . ./.env; . ./.env.live; set +a
```

## 2. Сеть и прокси

Если в сети нет прокси, этот раздел можно пропустить. Если прокси есть, учтите три правила:

- Переменная `all_proxy=socks5://…` ломает httpx: в проекте не установлен пакет `socksio`, и запросы падают
  с `ImportError … socksio`. Снимайте `all_proxy` и `ALL_PROXY`.
- HTTP-прокси (`http_proxy`, `https_proxy`) оставляйте. Через него доступен Telegram API.
  Напрямую из некоторых сетей Telegram отвечает `ConnectTimeout`.
- Polza через зарубежный прокси не отвечает. Добавьте её домены в `no_proxy`.

Итоговый префикс команд, которые ходят во внешние сервисы:

```bash
env -u all_proxy -u ALL_PROXY no_proxy="localhost,127.0.0.1,::1,polza.ai,.polza.ai" NO_PROXY="localhost,127.0.0.1,::1,polza.ai,.polza.ai" <команда>
```

Для обращений к локальному серверу используйте `curl --noproxy '*'`.

## 3. Запуск

Postgres в Docker, только на localhost. Пароль берётся из `.env`, он должен совпадать с `DATABASE_URL`:

```bash
set -a; . ./.env; set +a
docker run -d --name harness-pg -p 127.0.0.1:5432:5432 \
  -e POSTGRES_DB="$POSTGRES_DB" -e POSTGRES_USER="$POSTGRES_USER" -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  postgres:16-alpine
./tools/harness migrate                   # миграции до head
./tools/harness dev                       # server на 127.0.0.1:8000 и worker; остановка по Ctrl+C
```

Команду `./tools/harness dev` оставьте работать в отдельном окне. В другом терминале:

```bash
curl --noproxy '*' localhost:8000/health/ready
# {"status":"ready","database":true}
```

Предупреждение worker «workspace без repo.access_ref, задачи по ним уходят в error» — норма, пока у workspace нет ключа записи (D-60): такие задачи получают `error` с причиной `repo_access_ref`.

## 4. Публичный адрес для webhook

Telegram присылает обновления только на https-адрес. Для локальной работы подойдёт туннель localhost.run:

```bash
ssh -o ServerAliveInterval=30 -R 80:localhost:8000 nokey@localhost.run
```

Туннель выдаст адрес вида `https://<id>.lhr.life`. Окно с туннелем не закрывайте. При перезапуске туннеля
адрес меняется: пропишите новый адрес и повторите установку webhook.

Cloudflare quick tunnel (`cloudflared tunnel --url …`) в текущей сети не публикуется (DNS NXDOMAIN, ошибка edge 530),
его не используйте. Постоянный адрес даёт деплой в Dokploy с доменом, см. [deployment.md](deployment.md).

Затем пропишите адрес в `.env` и зарегистрируйте webhook:

```bash
set -a; . ./.env; set +a
# HARNESS_PUBLIC_URL=https://<id>.lhr.life — в .env
env -u all_proxy -u ALL_PROXY no_proxy="localhost,127.0.0.1,::1,polza.ai,.polza.ai" NO_PROXY="localhost,127.0.0.1,::1,polza.ai,.polza.ai" \
  uv run harness-server telegram set-webhook
# webhook установлен: https://<id>.lhr.life/telegram/webhook
```

После изменения `.env` перезапустите `./tools/harness dev`: переменные читаются при старте.

## 5. Работа через Telegram

Пишите боту из чата владельца:

| Что написать | Что ответит бот |
|---|---|
| «сделай …» (задача текстом) | Карточка `Задача [...] (выберите проект)` с кнопками кандидатов workspace |
| Нажатие кнопки проекта | Строка карточки меняется на `(проект «…», планирование)`, кнопки исчезают |
| «что сейчас в работе» | Список открытых задач из БД, без LLM и песочниц |
| Не относящийся к делу текст | Подсказка, задача не создаётся |
| Уверенность ниже `ROUTING_MIN_CONFIDENCE` | Кнопки «Сделать задачу / Показать статус»; задача создаётся только после нажатия |
| Голосовое сообщение | Карточка с расшифровкой; без `STT_*` — «не удалось распознать, пришлите текстом» |

Повторное нажатие на другую кнопку карточки отвечает «проект уже выбран».

## 6. Имитация апдейта без туннеля

Если туннеля нет, можно отправить апдейт на локальный сервер. Ответ бота всё равно придёт в настоящий чат.

Текстовое сообщение:

```bash
set -a; . ./.env; set +a
curl --noproxy '*' -X POST localhost:8000/telegram/webhook \
  -H "X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"update_id": <ts>, "message": {"message_id": <ts>, "date": <ts>, "chat": {"id": <chat_id>, "type": "private"}, "from": {"id": <chat_id>, "is_bot": false, "first_name": "Owner"}, "text": "<текст задачи>"}}'
```

Здесь `<ts>` — любое целое число, уникальное для каждого апдейта (например, текущее Unix-время), `<chat_id>` — значение
`TELEGRAM_CHAT_ID`.

Нажатие кнопки проекта:

```bash
curl --noproxy '*' -X POST localhost:8000/telegram/webhook \
  -H "X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"update_id": <ts>, "callback_query": {"id": "sim<ts>", "from": {"id": <chat_id>, "is_bot": false, "first_name": "Owner"}, "chat_instance": "sim", "data": "ws:<task_id без дефисов>:<workspace_id>", "message": {"message_id": <id карточки>, "date": <ts>, "chat": {"id": <chat_id>, "type": "private"}}}}'
```

Id карточки берётся из БД:

```bash
docker exec harness-pg psql -U harness -d harness -c "select message_id from telegram_messages where task_id='<uuid задачи>';"
```

Ограничения имитации: настоящая кнопка в Telegram без туннеля не сработает. Вызов `answerCallbackQuery` при
имитации завершится ошибкой в логе `./tools/harness dev`. Это ожидаемо.

## 7. Где смотреть результат

- Задача и лента событий: `GET /tasks/{id}` с заголовком `Authorization: Bearer $HARNESS_ADMIN_TOKEN`.

```bash
set -a; . ./.env; set +a
curl --noproxy '*' -H "Authorization: Bearer $HARNESS_ADMIN_TOKEN" localhost:8000/tasks/<uuid задачи>
```

- Решения маршрутизатора (таблица `routings`):

```bash
docker exec harness-pg psql -U harness -d harness -c "select created_at, decision, command_class, confidence, error, options from routings order by created_at desc limit 10;"
```

- Таблицы `tasks`, `telegram_updates` (колонка `processed_at` показывает, обработан ли апдейт)
  и `telegram_messages` — через `psql` тем же способом.
- Лог: окно, в котором запущен `./tools/harness dev`.

## 8. Подготовка проекта на машине агента

```bash
agent init <project>                      # подготовить проект из harness.yaml
```

- Команда клонирует репозиторий workspace из `harness.yaml`; ключ берётся из vault по `repo.access_ref` и доступен только git-команде этого проекта. Без ключа публичный репозиторий клонируется анонимно с предупреждением.
- Проект без маркера `projects/<id>.ready` не запускается: причина `project_not_initialized`. Повторный запуск `agent init` ещё не принят (задача 4.5 `local-agent-machine`).
- Состояние задач смотрите через `GET /tasks/{id}` и Telegram; CLI паузы для локальной машины нет.

## 9. Live-тесты

Live-тесты ходят во внешние сервисы и не запускаются по умолчанию. Живая проверка машины агента — TODO (задача 5.6 `local-agent-machine`). Запускайте их вручную с загруженными `.env` и `.env.live`
и с префиксом прокси из шага 2:

```bash
uv run pytest -m live apps/server/tests/test_polza_live.py          # маршрутизатор Polza
uv run pytest -m live apps/server/tests/test_agent_runtime_live.py  # activate → run_agent → wait_agent → cleanup_task
uv run pytest -m live apps/server/tests/test_telegram_live.py       # сообщение настоящим ботом
```

Агент работает по токену подписки Claude, поэтому расход идёт в лимиты этой подписки.

## 10. Остановка

- Окно `./tools/harness dev`: Ctrl+C.
- Окно туннеля: закрыть.
- Worker на хосте останавливается через свой systemd user unit; перед остановкой убедитесь, что активные процессы агента завершились. См. [deployment.md](deployment.md).
- Postgres: `docker stop harness-pg`. Данные сохраняются в контейнере. Удалить контейнер вместе с данными:
  `docker rm harness-pg`, если контейнер остановлен, или `docker rm -f harness-pg`, если работает.

## 11. Частые проблемы

| Симптом | Причина | Что делать |
|---|---|---|
| `ImportError … socksio` или 84 упавших теста | SOCKS-прокси в `all_proxy` | Снять `all_proxy` и `ALL_PROXY` |
| `telegram setWebhook failed: ConnectTimeout` | Telegram недоступен без прокси | Оставить `http_proxy`/`https_proxy` |
| `bad webhook: Failed to resolve host` | Туннель не опубликован | Использовать localhost.run (шаг 4) |
| В логе `routing failed: timeout`, карточка со всеми проектами | Polza идёт через прокси | Добавить `polza.ai,.polza.ai` в `no_proxy` |
| Сервер не стартует, `TELEGRAM_CHAT_ID` пустой | Переменная не задана | Заполнить по инструкции из шага 1 |

Остальные ошибки конфигурации сервер печатает с именем переменной, например `некорректные ENV: TELEGRAM_BOT_TOKEN: Field required`.
Сравните имя переменной с таблицей из шага 1.

См. также: [development.md](development.md), [deployment.md](deployment.md), [apps/server/README.md](../apps/server/README.md).
