# apps/server — сервер и worker

Пакет `harness_server`: FastAPI-приложение, worker и CLI `harness-server`. Бизнес-логика задач —
в `services/tasks.py` (mvp-03); входы (`api/`, позже `mcp/`, `telegram/`, CLI) только вызывают её.

## Команды CLI

| Команда | Что делает |
|---|---|
| `harness-server --help` | Справка по командам |
| `harness-server check-config` | Проверяет ENV и `harness.yaml`, печатает список workspace |
| `harness-server serve --host 127.0.0.1 --port 8000` | HTTP-сервер: `GET /health`, `GET /health/ready`. По умолчанию слушает localhost; в контейнере `--host 0.0.0.0` |
| `harness-server worker` | Цикл опроса очереди задач. При старте восстанавливает апдейты Telegram: необработанные старше 1 мин обрабатываются заново, старше 24 ч списываются без обработки (payload очищается), недостающие карточки досылаются. Остановка по SIGTERM |
| `harness-server migrate` | `alembic upgrade head`, нужен `DATABASE_URL` |
| `harness-server telegram set-webhook` | Регистрирует webhook в Telegram: адрес `HARNESS_PUBLIC_URL` + `/telegram/webhook` (только https), секрет из `TELEGRAM_WEBHOOK_SECRET`. Выполняется после деплоя и при смене адреса; ошибки — код 1 без токена и секрета в выводе |
| `harness-server sandbox status` | Строка песочницы из `harness.yaml`: статус и закреплённая задача (нужен `DATABASE_URL`) |
| `harness-server sandbox bootstrap [--script deploy/sandbox/bootstrap.sh]` | Подготавливает песочницу скриптом: версии `claude`/`openspec`, каталоги, клоны. Нужны `NOVITA_API_KEY`, `GITLAB_TOKEN`; вывод проходит redaction |
| `harness-server sandbox pause` / `resume` | Пауза и возобновление песочницы. Пауза отказывает (код 1), если за песочницей закреплена задача; `resume` сбрасывает `error` в `paused` после успешного connect, если за песочницей не закреплена задача; иначе — ручной разбор (см. [docs/deployment.md](../../docs/deployment.md)) |

## HTTP-эндпоинты задач

| Метод и путь | Что делает | Ответ |
|---|---|---|
| `POST /tasks` | Создаёт задачу `plan` в статусе `new`, источник `api`. Тело: `text` (1–20 000 символов), необязательный `workspace_id` | `201` с задачей; `422` при `unknown_workspace` или пустом тексте |
| `GET /tasks/{id}` | Задача и лента событий в хронологическом порядке | `200`; `404`, если задачи нет |

Оба требуют заголовок `Authorization: Bearer <HARNESS_ADMIN_TOKEN>` (временный доступ, D-23). Без заголовка,
с другой схемой, неверным токеном или когда `HARNESS_ADMIN_TOKEN` не задан — `401` с `WWW-Authenticate: Bearer`
и телом `{"detail": "unauthorized"}`, без проверки существования задачи. `HARNESS_ADMIN_TOKEN`, если задан,
должен быть не короче 32 символов без пробелов по краям: короткий токен роняет запуск сервера целиком,
пустой считается не заданным, и `/tasks` тогда всегда отвечает 401.

`serve`, `worker` и `check-config` перед стартом проверяют ENV и `harness.yaml`. При ошибке они
печатают имя переменной или путь к полю без значений и выходят с кодом 1, например:

```
Ошибка конфигурации: некорректные ENV: TELEGRAM_BOT_TOKEN: Field required
```

## Конфигурация

- ENV: обязательные и опциональные переменные описаны в [ARCHITECTURE.md §9](../../ARCHITECTURE.md)
  и в `.env.example`. Секреты читаются как `SecretStr`.
- `harness.yaml`: пример в `config/harness.example.yaml`. Файл с настройками workspace; ключи
  вида `token`, `key`, `password`, `secret`, `apikey`, `credential` (и их варианты во множественном числе,
  `passwd`, `pwd`) сервер отклоняет; `gitlab.base_url` с учётными данными тоже.

## Запуск

Из корня репозитория:

```bash
uv sync
cp .env.example .env                  # заполнить секреты
cp config/harness.example.yaml config/harness.yaml
./tools/harness dev                   # server на :8000 и worker
```

`/health` отвечает без Postgres. `/health/ready` без доступной БД отвечает 503.

## Тесты

```bash
./tools/harness check                 # ruff, ruff format, mypy strict, pytest
uv run pytest                         # только тесты
```

Тесты с БД используют `TEST_DATABASE_URL`, если он задан (так в CI), иначе поднимают Postgres
через testcontainers (нужен Docker). Тесты с маркером `live` (реальные внешние сервисы) по
умолчанию не запускаются.

### Живая проверка Telegram (`-m live`)

Тест `tests/test_telegram_live.py` отправляет и правит сообщение настоящим ботом. Нужны переменные
`LIVE_TELEGRAM_BOT_TOKEN` (токен бота) и `LIVE_TELEGRAM_CHAT_ID` (чат владельца). Без них тест пропускается.

```bash
uv run pytest -m live apps/server/tests/test_telegram_live.py
```

Ручной сценарий (задача 4.3 в OpenSpec `mvp-04-telegram-intake`, выполняет владелец проекта):

1. Сервер и worker запущены с настройками из `.env`, миграции применены (`harness-server migrate`).
2. `harness-server telegram set-webhook`: команда печатает `webhook установлен: https://…/telegram/webhook`.
3. Текстом из чата владельца отправить «добавь экспорт в CSV»: бот присылает карточку задачи с кнопками
   по всем workspace и строкой `Задача [добавь экспорт в CSV] (выберите проект)`.
4. Голосовым сообщением (до 20 МиБ, OGG) создать задачу: карточка содержит расшифровку. Если STT
   не настроен или провайдер отклонил файл, бот отвечает «не удалось распознать, пришлите текстом»
   и задачи не создаёт.
5. Нажать кнопку workspace: строка карточки меняется на `(проект «…», планирование)`, клавиатура
   исчезает. Повторное нажатие на другую кнопку отвечает «проект уже выбран».

Результат прогона записать в PR. Чекбокс 4.3 закрывает владелец проекта после проверки.

Пошаговая работа с харнессом без UI, включая проверку через Telegram и CLI: [docs/operating-without-ui.md](../../docs/operating-without-ui.md).

### Живая проверка песочницы (`-m live`)

Тесты `tests/test_novita_live.py` работают с настоящей песочницей Novita и запускаются владельцем вручную.
Нужны `LIVE_NOVITA_API_KEY`, `LIVE_NOVITA_SANDBOX_ID` и `LIVE_CLAUDE_CODE_OAUTH_TOKEN`; без них тесты
пропускаются. Проверяют exec, запись и чтение файлов, pause/connect, многоходовой `claude -p` с
`--max-turns 1` и изоляцию (hook из `.claude/settings.json` и сервер из `.mcp.json` worktree не срабатывают),
а также отсутствие значения токена на диске песочницы (`grep -rF`).

```bash
LIVE_NOVITA_API_KEY=… LIVE_NOVITA_SANDBOX_ID=… LIVE_CLAUDE_CODE_OAUTH_TOKEN=… \
  uv run pytest -m live apps/server/tests/test_novita_live.py
```

## Маршрутизация текста владельца (mvp-05)

Каждый текст и голос владельца классифицируется вызовом Polza (`adapters/polza`, D-31): класс `work`, `status`
или `unknown`, до трёх кандидатов workspace. При временной ошибке Polza выполняется один повтор, то есть не больше
двух платных запросов на сообщение. Промпт — `src/harness_server/services/prompts/routing.md`
(входит в wheel, проверяется командой сборки). Маршрутизатор включается только при заданных `POLZA_AI_KEY`
и `POLZA_AI_MODEL`; модель в коде по умолчанию не задана и выбирается владельцем. Без них работает запасной путь
mvp-04: задача со всеми workspace.

- Порог `ROUTING_MIN_CONFIDENCE` (по умолчанию 0.6): ниже порога бот спрашивает «Сделать задачу / Показать статус»,
  задача не создаётся до нажатия (D-33).
- `status` отвечает списком открытых задач из БД, без LLM и песочниц (D-34).
- Каждое решение пишется в `routings` (D-32), в том числе причина запасного пути и сырой ответ модели после redaction.

### Живая проверка маршрутизатора (`-m live`)

Тест `tests/test_polza_live.py` вызывает настоящий Polza. Нужны `LIVE_POLZA_API_KEY` и `LIVE_POLZA_MODEL`,
необязательно `LIVE_POLZA_URL`. Без переменных тест пропускается.

```bash
LIVE_POLZA_API_KEY=… LIVE_POLZA_MODEL=… uv run pytest -m live apps/server/tests/test_polza_live.py
```

Ручной сценарий (задача 5.2 в OpenSpec `mvp-05-command-routing`, выполняет владелец проекта): 10 реальных фраз
(5 работа, 3 статус, 2 мусор), часть голосом; для каждой фиксируются класс, уверенность и кандидаты. Таблица
«фраза → класс, confidence, кандидаты» идёт в MR. Модель выбирает владелец: она должна поддерживать
`response_format: json_object` и хорошо работать с русским. Чекбокс 5.2 закрывает владелец проекта после проверки.

## Структура

```
src/harness_server/
├── settings.py     # Settings: ENV, секреты как SecretStr
├── config.py       # HarnessConfig: harness.yaml, запрет секретов в файле
├── app.py          # create_app(settings, config): FastAPI и lifespan с engine БД
├── wiring.py       # композиционный корень бота: httpx-клиент, BotAdapters, BotContext (D-29)
├── api/health.py   # /health и /health/ready
├── api/tasks.py    # POST /tasks, GET /tasks/{id}
├── api/telegram_webhook.py  # POST /telegram/webhook: секрет, фильтр чата, запись апдейта, фон
├── api/deps.py     # сессия БД, конфиг, HARNESS_ADMIN_TOKEN, секрет webhook, BotContext
├── services/tasks.py  # создание, смена статуса, выбор workspace, лента, очередь claim_next_task
├── services/intake.py # приём и обработка апдейтов, STT, выбор проекта, recover_pending при старте worker
├── services/notify.py # одно обновляемое сообщение задачи, reply, вопрос уточнения (mvp-05)
├── services/routing.py      # классификация Polza, уточнение, запись routings (mvp-05)
├── services/status_report.py # ответ на запрос состояния из БД, без LLM (mvp-05)
├── services/prompts/routing.md # системный промпт маршрутизатора (mvp-05)
├── services/webhook.py  # webhook_url, register_webhook (set-webhook)
├── services/sandboxes.py # токены задач, резервирование песочницы, активация, запуск и опрос агента, очистка, пауза (mvp-06)
├── services/agent_result.py # parse_result (событие result потока), parse_exit_code, parse_pid (mvp-06)
├── adapters/novita/     # protocol.py (SandboxProvider), client.py (NovitaSandboxProvider на AsyncSandbox), errors.py, fake.py (FakeSandbox) (mvp-06)
├── worker/              # __init__.py (цикл worker), dispatcher.py (шаги песочницы), pipeline.py (контракт Pipeline, реестр пуст до mvp-08)
├── services/context.py  # BotContext: фабрика сессий, адаптеры, workspace, владелец
├── telegram/parse.py    # update → IncomingText | IncomingVoice | ButtonPress, dedup_key (без I/O)
├── telegram/render.py   # тексты, карточка задачи, callback_data, клавиатура (без I/O)
├── adapters/telegram/   # Protocol TelegramClient, HttpxTelegramClient, FakeTelegramClient, ошибки без URL и токена
├── adapters/stt/        # Protocol SpeechToText, OpenAiCompatibleStt, FakeSpeechToText
├── adapters/polza/      # Protocol Router, PolzaRouter (httpx, chat completions), FakeRouter (mvp-05)
├── security/redaction.py  # redact(): шаблоны токенов и точные значения секретов
├── domain/         # statuses.py (таблица переходов), errors.py (DomainError)
├── db/             # base, ids (uuid7), session, models/ (ORM 9 таблиц), migrations/ (0001–0003)
├── worker.py       # start_worker (восстановление апдейтов, BotContext), цикл и обработка SIGTERM
└── cli.py          # команды harness-server (typer), telegram set-webhook
```

Модели ответов, видимые снаружи, лежат в `shared/` (пакет `harness_shared`).
