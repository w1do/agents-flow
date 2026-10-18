# Design: mvp-04-telegram-intake

Документ — исполняемая спецификация для Implementer. Имена файлов, символов, сигнатур, строк бота и тестов
обязательны. Если что-то из написанного невозможно (ошибка mypy, Alembic или поведение библиотеки, которое
нельзя обойти без отступления от текста), Implementer останавливается и сообщает, а не придумывает замену.

## Context: текущее состояние (mvp-03, проверено по коду через project-memory)

- `app.py::create_app(settings, config)` — lifespan создаёт engine (`db/session.py::create_engine`),
  `app.state.session_factory`, `app.state.settings`, `app.state.config`; роутеры `api/health.py`, `api/tasks.py`.
- `api/deps.py` — `get_session` (сессия на запрос), `get_config`, `require_admin_token` (sha256 + `hmac.compare_digest`,
  401 `{"detail":"unauthorized"}`), `SessionDep`, `ConfigDep`. Авторизация `/tasks` — router-зависимость.
- `settings.py::Settings` — уже есть `telegram_bot_token: SecretStr`, `telegram_chat_id: str`,
  `telegram_webhook_secret: SecretStr` (валидатор `_check_webhook_secret_format`, regex `[A-Za-z0-9_-]{1,256}`),
  `harness_public_url: str | None`, `stt_provider: str | None`, `stt_api_url: str | None`, `stt_api_key: SecretStr | None`,
  `stt_model: str | None`, `worker_poll_interval_sec`. `load_settings()` → `SettingsError` без значений.
- `config.py::WorkspaceConfig` — `id: str = Field(min_length=1)` без ограничения длины и алфавита, `name`,
  `voice_aliases`, …; `HarnessConfig.workspaces` (≥ 1, уникальные id).
- `services/tasks.py` — `create_task(session, *, kind, text, source, known_workspace_ids, workspace_id=None, …)`,
  `get_task`, `list_task_events`, `list_tasks`, `change_status(session, task_id, to_status, *, source, text=None)`
  (FOR UPDATE + событие + commit), `add_event`, `claim_next_task`. Каждая функция сама делает commit (D-24).
  Функции установки workspace нет.
- `domain/statuses.py::TRANSITIONS[PLAN]`: `new → {choosing}`, `choosing → {planning, trash}`,
  `planning → {ready, error}` — нужные переходы разрешены. `domain/errors.py`: `DomainError`, `InvalidTransition`,
  `InvalidStatus`, `UnsupportedKind`, `UnknownWorkspace`, `NotFound`, `Forbidden`.
- `harness_shared.tasks`: `TaskKind`, `TaskStatus`, `TaskSource.TELEGRAM`, `TaskEventSource.TELEGRAM`, `TaskText`
  (≤ 20 000 символов).
- `db/models/telegram.py`: `TelegramMessage` (PK `task_id`, `chat_id` BigInteger, `message_id` BigInteger,
  `lines` JSONB `list[str]`, `TimestampMixin`); `TelegramUpdate` (PK `kind` + `external_id` String(64), CHECK
  `kind IN ('update','callback')`, `received_at`, `processed_at`). **Тела апдейта нет** — задача 2.3 на этой схеме
  невыполнима (решение пользователя: миграция `0002`, D-27).
- `db/migrations/versions/20261018_0001_initial.py` — ревизия `0001`, ручная, без импорта `harness_server`.
- `worker.py` — `run_worker(poll_interval_sec, stop)` (лог `worker started, …`), `serve_worker(poll_interval_sec)`
  (обработчики SIGTERM/SIGINT). К БД не обращается. `cli.py::worker` вызывает
  `asyncio.run(serve_worker(settings.worker_poll_interval_sec))`.
- `cli.py` — typer `app`, `_configure_logging()` (root INFO), `_load_or_exit()`, команды `serve`, `worker`, `migrate`,
  `check-config`. Логгер `httpx` на уровне INFO пишет полный URL запроса — для Telegram это токен бота в логе.
- Пакетов `adapters/`, `security/`, `telegram/` ещё нет. `httpx` — зависимость сервера; `respx`, `asgi-lifespan`,
  `pytest-asyncio`, `testcontainers` — dev-зависимости корня. Новых зависимостей не требуется.
- `tests/conftest.py` — `clean_env` (autouse, список `ALL_ENV_NAMES`), `valid_env` (`TELEGRAM_CHAT_ID="424242"`),
  `migrated_database_url`, `db_engine`, `db_session` (SAVEPOINT), `committed_session_factory` (реальные коммиты +
  `TRUNCATE_ALL`). Тест `test_settings.py::test_webhook_secret_accepts_telegram_alphabet` использует секрет
  `"Abc_123-xyz"` (11 символов) — после задачи 6.1 он должен стать длиннее 32 символов.
- `docker-compose.yml` перечисляет переменные явно (`WORKER_POLL_INTERVAL_SEC: ${WORKER_POLL_INTERVAL_SEC:-}`).
- `pyproject.toml`: `addopts = "-m 'not live'"`, маркер `live` объявлен.

## Goals / Non-Goals

**Goals:** ни одного дубля задачи при повторной доставке; ответ webhook без ожидания STT и Telegram; никакой
реакции и никакой записи для чужих чатов; апдейт, принятый перед рестартом, не теряется; текст апдейта не
хранится после обработки.

**Non-Goals:** см. proposal.md («Не входит»). Конвертация OGG и длинные голосовые — `voice-robustness`.

## Decisions

Каждое решение — с отвергнутой альтернативой. Номера — в docs/decisions.md.

1. **Приём и обработка разделены.** Webhook проверяет секрет, разбирает апдейт, отбрасывает чужие чаты, вставляет
   строку в `telegram_updates` (`INSERT … ON CONFLICT DO NOTHING RETURNING`) вместе с нормализованным апдейтом в
   `payload`, ставит `process_recorded` в `BackgroundTasks` и отвечает `200`. Отвергнуто: синхронная обработка —
   таймаут Telegram во время STT и повторная доставка.
2. **`telegram_updates.payload JSONB NULL` — миграция `0002`** (D-27, решение пользователя). В `payload` пишется
   не сырой апдейт, а `IncomingText | IncomingVoice | ButtonPress` (`model_dump(mode="json")`): без `from`, имён
   и username. После обработки `payload = NULL`, `processed_at = now()`. Чужие чаты не пишутся вообще.
   Необработанный апдейт старше `PAYLOAD_TTL` (24 ч) не выполняется: `processed_at = now()`, `payload = NULL`
   без обработки (S2a, `services/intake.py`). Очистка идёт только при старте worker (`recover_pending`), периодической
   очистки нет: просроченная строка, которой не дошла очередь старта, остаётся до следующего старта.
   Отвергнуто: хранить сырой JSON — лишние персональные данные; хранить только ключ — нечего дообрабатывать.
3. **Защита от параллельной обработки одного апдейта** — строка `telegram_updates` блокируется
   `SELECT … FOR UPDATE SKIP LOCKED` в отдельной «сессии-замке» на всё время обработки; занятая или уже
   обработанная строка пропускается. Отвергнуто: отметка `processed_at` в начале обработки — сбой посередине
   терял бы апдейт навсегда.
4. **Порядок шагов сообщения:** STT → `create_task` → `change_status(choosing)` → отметка апдейта обработанным →
   отправка карточки с кнопками. Сбой Telegram при отправке карточки не создаёт дубль задачи: задача остаётся в
   `choosing` без строки `telegram_messages`, и восстановление при старте worker досылает карточку. Отвергнуто:
   отметка после отправки карточки — сбой Telegram давал бы повторное создание задачи.
5. **Восстановление при старте worker** (`services/intake.py::recover_pending`): апдейты
   `processed_at IS NULL AND received_at < now() − 1 мин` обрабатываются заново через `process_recorded`; задачи
   `source = telegram` в `new`/`choosing` старше 1 мин без `telegram_messages` получают карточку (`new` сначала
   переводится в `choosing`). Апдейты старше `PAYLOAD_TTL` = 24 ч списываются без обработки (см. решение 2).
   Ошибки восстановления логируются без трассировки и не мешают запуску worker.
6. **callback_data = `ws:<task.id.hex>:<workspace_id>`** (D-28). `task_short` — это `task.id.hex` (32 hex-символа
   UUIDv7 без дефисов): однозначный поиск задачи без отдельной таблицы. Префикс и разделители — 4 байта, итого
   36 байт, на `workspace_id` остаётся ≤ 28 байт. Поэтому `WorkspaceConfig.id` ограничивается
   `^[A-Za-z0-9_-]+$` и `max_length=28` (ASCII: байты = символы; `:` запрещён). Отвергнуто: индекс workspace в
   списке — при смене `harness.yaml` кнопка выбрала бы чужой проект; префикс UUID — у UUIDv7 первые 12 hex —
   миллисекунды, коллизии.
7. **Список workspace для кнопок** — все `config.workspaces` в порядке `harness.yaml`, по одной кнопке в ряд,
   подпись — `WorkspaceConfig.name`. Ранжирование — `mvp-05`.
8. **Повторное нажатие** на задачу не в `choosing` → `InvalidTransition` из `services.tasks.select_workspace` →
   `answer_callback_query(text="проект уже выбран")`, статус и workspace не меняются, событие не пишется.
9. **Одно сообщение на задачу** (`services/notify.py::append_stage`): строка `TelegramMessage` блокируется
   `FOR UPDATE`, строка этапа дописывается, текст перерисовывается и отправляется `editMessageText` без
   клавиатуры (Bot API: без `reply_markup` инлайн-клавиатура убирается). «message is not modified» — успех.
   «message can't be edited» / «message to edit not found» / `MESSAGE_ID_INVALID` — `MessageNotEditable` →
   новое сообщение, `message_id` обновляется. Определение — по `error_code == 400` и подстроке в
   `description.lower()`, не по точному тексту. Прочие ошибки Telegram логируются, строки этапов всё равно
   сохраняются (следующая правка покажет все).
10. **STT** (D-05, D-29): файл скачивается в память с лимитом `VOICE_MAX_BYTES` (по умолчанию и максимум 20 МиБ —
    лимит `getFile`), отправляется **как есть**: имя `voice.ogg`, MIME из апдейта (`audio/ogg`, если нет).
    OGG/Opus нет в официальном списке форматов OpenAI — риск, см. Risks; конвертация — `voice-robustness`.
    Любая ошибка (нет настроек STT, файл больше лимита, ошибка Telegram, ошибка/пустой ответ STT) → ответ
    «не удалось распознать, пришлите текстом», задача не создаётся.
11. **Внедрение адаптеров** (D-29): композиционный корень `harness_server/wiring.py` строит httpx-клиент,
    адаптеры (`BotAdapters`) и `services/context.py::BotContext`. `create_app(settings, config, *, adapters=None)` и
    `worker.start_worker(..., adapters=None)` принимают фейки в тестах. Webhook получает контекст через
    `api/deps.py::get_bot_context` (`app.state.bot`). Отвергнуто: глобальные синглтоны — тесты не подменят адаптер.
12. **Утечки токена** (D-29): токен Telegram — часть URL. `TelegramError` никогда не содержит URL и текст исключения
    httpx (только имя класса); `cli._configure_logging` поднимает логгеры `httpx` и `httpcore` до WARNING. Ключ STT
    передаётся только заголовком; `SttError` его не содержит. Логи обработки — только ключ апдейта, id задачи и
    имя класса ошибки, без текста задачи и без трассировки (в трассировке SQLAlchemy — параметры запроса).
13. **Тексты, уходящие в Telegram, проходят `security/redaction.py::redact`** с точными значениями всех `SecretStr`
    из `Settings` (`wiring.secret_values`). Значения короче 8 символов не заменяются.
    Очистка идёт раньше обрезки и раньше записи: текст входящего сообщения и расшифровка STT проходят redact до
    `create_task` (в `tasks.text` секрета нет), а заголовок и карточка строятся из уже очищенного текста, поэтому
    усечение не оставляет от токена фрагмент (S4). `_answer` тоже проходит через redact. `db/session.py` создаёт
    engine с `hide_parameters=True`: параметры запроса SQLAlchemy не попадают в трассировки и логи (S3).
14. **Команды `/…` не являются задачами:** текст, начинающийся с `/` (например, `/start`), `parse_update` возвращает
    как `None`. Команды — `mvp-05` и далее.
15. **Владелец — только личный чат** (D-30): `TELEGRAM_CHAT_ID` принимается только положительным id. Групповые чаты
    не поддерживаются, потому что авторизация идёт по `chat_id` (C6), и в группе любой участник создавал бы задачи.
    Проверка `from.id` — при появлении групп отдельным изменением.
15. **Модели Telegram внутренние.** `IncomingText`, `IncomingVoice`, `ButtonPress` и типы адаптера не видны MCP, API
    и консоли, поэтому живут в `telegram/parse.py` и `adapters/telegram/types.py`, а не в `shared/`. В `shared/`
    ничего не добавляется.
16. **6.1 (хвост mvp-02):** `TELEGRAM_WEBHOOK_SECRET` — от 32 до 256 символов `A-Za-z0-9_-` (как
    `HARNESS_SECRET_KEY`). `TELEGRAM_CHAT_ID` — целое число (может быть отрицательным для групп).
    `STT_PROVIDER` — только `openai` (OpenAI-совместимый протокол) или не задан.

## Файлы и символы

Все пути серверного кода — от `apps/server/src/harness_server/`.

### Новые файлы

| Путь | Содержимое |
|---|---|
| `adapters/__init__.py` | docstring: «Адаптеры внешних API: Protocol, реализация и фейк для тестов.» |
| `adapters/telegram/__init__.py` | реэкспорт: `TelegramClient`, `HttpxTelegramClient`, `FakeTelegramClient`, `TelegramError`, `MessageNotEditable`, `FileTooLarge`, `InlineButton`, `InlineKeyboard`, `TelegramFile` (+ `__all__`) |
| `adapters/telegram/types.py` | `InlineButton`, `InlineKeyboard`, `TelegramFile`, `TelegramError`, `MessageNotEditable`, `FileTooLarge` |
| `adapters/telegram/protocol.py` | `TelegramClient` (Protocol) |
| `adapters/telegram/client.py` | `HttpxTelegramClient`, `TELEGRAM_API_URL` |
| `adapters/telegram/fake.py` | `FakeTelegramClient`, `SentMessage`, `EditedMessage` |
| `adapters/stt/__init__.py` | реэкспорт: `SpeechToText`, `SttError`, `OpenAiCompatibleStt`, `FakeSpeechToText` |
| `adapters/stt/protocol.py` | `SpeechToText` (Protocol), `SttError` |
| `adapters/stt/openai_compat.py` | `OpenAiCompatibleStt` |
| `adapters/stt/fake.py` | `FakeSpeechToText` |
| `security/__init__.py` | docstring: «Фильтр секретов и (с mvp-07) токены задач.» |
| `security/redaction.py` | `REDACTED`, `redact()` |
| `telegram/__init__.py` | docstring: «Разбор апдейтов и рендер сообщений Telegram. Без I/O и без БД.» |
| `telegram/parse.py` | `UpdateKind`, `IncomingText`, `IncomingVoice`, `ButtonPress`, `Incoming`, `parse_update`, `dump_incoming`, `load_incoming`, `dedup_key` |
| `telegram/render.py` | константы текстов, `short_title`, `stage_line`, `planning_stage`, `render_card`, `build_callback_data`, `parse_callback_data`, `workspace_keyboard` |
| `services/context.py` | `BotContext` |
| `services/intake.py` | `STALE_AFTER`, `PAYLOAD_TTL`, `MAX_TASK_TEXT`, `record_incoming`, `process_recorded`, `choose_workspace`, `recover_pending` |
| `services/notify.py` | `send_task_card`, `append_stage`, `reply` |
| `services/webhook.py` | `WEBHOOK_PATH`, `ALLOWED_UPDATES`, `webhook_url`, `register_webhook` |
| `api/telegram_webhook.py` | `router`, `telegram_webhook` |
| `wiring.py` | `BotAdapters`, `build_http_client`, `build_adapters`, `secret_values`, `build_bot_context` |
| `db/migrations/versions/20261018_0002_telegram_update_payload.py` (от корня репо) | ревизия `0002` |
| `apps/server/tests/fixtures/telegram/*.json` | 6 записанных апдейтов (см. Test strategy) |
| `apps/server/tests/test_telegram_client.py`, `test_stt_client.py`, `test_redaction.py`, `test_telegram_parse.py`, `test_telegram_render.py`, `test_telegram_webhook.py`, `test_intake_service.py`, `test_notify_service.py`, `test_recovery.py`, `test_webhook_service.py`, `test_telegram_live.py` | тесты |

### Изменяемые файлы

`settings.py`, `config.py`, `app.py`, `api/deps.py`, `cli.py`, `worker.py`, `services/tasks.py`,
`db/models/telegram.py`; тесты `conftest.py`, `test_settings.py`, `test_config.py`, `test_cli.py`,
`test_task_service.py`, `test_migrations.py`, `test_worker.py`; документация (см. «Разрешённые файлы»).

## Proposed architecture

```
Telegram ──POST /telegram/webhook──► api/telegram_webhook.py
                                        │ Depends: require_webhook_secret, SessionDep, BotContextDep
                                        ├─► telegram/parse.py::parse_update        (чистая функция)
                                        ├─► services/intake.py::record_incoming    (INSERT … ON CONFLICT)
                                        └─► BackgroundTasks: services/intake.py::process_recorded
                                                 ├─ IncomingText/Voice ─► adapters/stt, services/tasks.create_task,
                                                 │                        change_status, services/notify.send_task_card
                                                 └─ ButtonPress ─► services/intake.choose_workspace
                                                                    ─► services/tasks.select_workspace,
                                                                       services/notify.append_stage

worker.py::start_worker ─► services/intake.py::recover_pending ─► process_recorded / send_task_card
cli.py telegram set-webhook ─► services/webhook.py::register_webhook ─► TelegramClient.set_webhook

wiring.py: httpx.AsyncClient → HttpxTelegramClient, OpenAiCompatibleStt → BotAdapters → BotContext
services/notify.py ─► telegram/render.py (чистые функции), security/redaction.py
```

Правила: `api/telegram_webhook.py` не импортирует `sqlalchemy` и модели БД, вызывает только `services.intake` и
`telegram.parse`. `adapters/*` не импортируют `db`, `services`, `domain`. `telegram/*` не делает I/O и не
импортирует `db`/`services`. `services/*` не импортируют `httpx` и реализации адаптеров — только `protocol`/`types`.

## Detailed specification

### 1. `adapters/telegram/types.py`

```python
from dataclasses import dataclass

_DESCRIPTION_LIMIT = 200


@dataclass(frozen=True, slots=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True, slots=True)
class InlineKeyboard:
    rows: tuple[tuple[InlineButton, ...], ...]

    def to_api(self) -> dict[str, list[list[dict[str, str]]]]:
        """{"inline_keyboard": [[{"text": …, "callback_data": …}, …], …]}"""


@dataclass(frozen=True, slots=True)
class TelegramFile:
    file_id: str
    file_path: str | None
    file_size: int | None


class TelegramError(Exception):
    """Ошибка Bot API или сети. Сообщение без URL и токена: только метод, код и описание Telegram."""

    def __init__(self, method: str, error_code: int | None, description: str) -> None:
        short = description[:_DESCRIPTION_LIMIT]
        super().__init__(f"telegram {method} failed: {error_code} {short}")
        self.method = method
        self.error_code = error_code
        self.description = short


class MessageNotEditable(TelegramError):
    """Сообщение нельзя отредактировать (удалено, старое, чужое) — нужно отправить новое."""


class FileTooLarge(TelegramError):
    """Файл больше разрешённого лимита."""
```

### 2. `adapters/telegram/protocol.py`

```python
class TelegramClient(Protocol):
    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: InlineKeyboard | None = None
    ) -> int: ...  # возвращает message_id
    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: InlineKeyboard | None = None,
    ) -> None: ...  # «not modified» — успех; недоступно — MessageNotEditable
    async def answer_callback_query(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None: ...
    async def get_file(self, file_id: str) -> TelegramFile: ...
    async def download_file(self, file_path: str, *, max_bytes: int) -> bytes: ...
    async def set_webhook(
        self, url: str, *, secret_token: str, allowed_updates: Sequence[str]
    ) -> None: ...
```

Каждый метод при ошибке бросает `TelegramError` (или подкласс). Docstring у класса и методов.

### 3. `adapters/telegram/client.py`

```python
TELEGRAM_API_URL = "https://api.telegram.org"
# Общий дедлайн скачивания файла (S5): зависший поток не держит worker; по истечении — TelegramError без URL.
DOWNLOAD_TIMEOUT_SEC: Final = 60.0


class HttpxTelegramClient:
    """Тонкий клиент Bot API на httpx (D-14). httpx.AsyncClient принадлежит вызывающему."""

    def __init__(self, token: str, http: httpx.AsyncClient, *, base_url: str = TELEGRAM_API_URL) -> None
    def __repr__(self) -> str            # "HttpxTelegramClient()" — без токена
    async def _call(self, method: str, payload: dict[str, Any]) -> Any
```

`_call`:
1. `url = f"{base_url}/bot{token}/{method}"`; `response = await http.post(url, json=payload)`.
2. `except httpx.HTTPError as exc: raise TelegramError(method, None, type(exc).__name__) from None`.
3. `body = response.json()`; `ValueError` или не `dict` → `TelegramError(method, response.status_code, "invalid response")`.
4. `body.get("ok") is True` → вернуть `body.get("result")`.
5. Иначе `TelegramError(method, error_code if isinstance(error_code, int) else response.status_code,
   description if isinstance(description, str) else "unknown error")`.

Методы:
- `send_message`: payload `{"chat_id": chat_id, "text": text}` + `"reply_markup": reply_markup.to_api()` если задан;
  `parse_mode` не передаётся (простой текст, без разметки). Результат — `dict` с `int` `message_id`, иначе
  `TelegramError("sendMessage", None, "invalid response")`.
- `edit_message_text`: payload `{"chat_id", "message_id", "text"}` (+ `reply_markup`, если задан). Обработка
  `TelegramError exc`:
  `d = exc.description.lower()`; если `exc.error_code == 400 and "message is not modified" in d` → `return`;
  если `exc.error_code == 400 and any(s in d for s in ("can't be edited", "to edit not found", "message_id_invalid"))`
  → `raise MessageNotEditable(exc.method, exc.error_code, exc.description) from None`; иначе `raise`.
- `answer_callback_query`: payload `{"callback_query_id": …}` + `"text"` если задан.
- `get_file`: payload `{"file_id": …}`; результат `dict` → `TelegramFile(file_id=str(result["file_id"]),
  file_path=result.get("file_path") if str, file_size=result.get("file_size") if int)`; иначе `invalid response`.
- `download_file`: если `file_path.startswith("/")` или `".." in file_path` → `TelegramError("downloadFile", None,
  "invalid file path")`. `async with http.stream("GET", f"{base_url}/file/bot{token}/{file_path}") as response:`;
  `status_code != 200` → `TelegramError("downloadFile", status_code, "download failed")`; читать
  `response.aiter_bytes()`, при сумме > `max_bytes` → `FileTooLarge("downloadFile", None, "file too large")`.
  `httpx.HTTPError` → `TelegramError("downloadFile", None, type(exc).__name__) from None`.
- `set_webhook`: payload `{"url": url, "secret_token": secret_token, "allowed_updates": list(allowed_updates)}`.

### 4. `adapters/telegram/fake.py`

```python
@dataclass
class SentMessage:
    chat_id: int
    message_id: int
    text: str
    reply_markup: InlineKeyboard | None


@dataclass
class EditedMessage:
    chat_id: int
    message_id: int
    text: str
    reply_markup: InlineKeyboard | None


class FakeTelegramClient:
    """Фейк TelegramClient: пишет вызовы в списки, хранит текущий текст сообщений."""

    def __init__(self, *, files: Mapping[str, bytes] | None = None) -> None:
        self.sent: list[SentMessage] = []
        self.edits: list[EditedMessage] = []
        self.callback_answers: list[tuple[str, str | None]] = []
        self.webhooks: list[tuple[str, str, tuple[str, ...]]] = []
        self.files: dict[str, bytes] = dict(files or {})
        self.texts: dict[int, str] = {}  # message_id → текущий текст
        self.not_editable: set[int] = set()
        self.fail_with: TelegramError | None = None  # если задан — каждый метод бросает его
        self._next_message_id = 100
```

- `send_message`: `fail_with` → raise; `message_id = self._next_message_id`, затем `+= 1`; запись в `sent` и `texts`.
- `edit_message_text`: `fail_with` → raise; `message_id in not_editable or message_id not in texts` →
  `MessageNotEditable("editMessageText", 400, "Bad Request: message to edit not found")`; запись в `edits`, `texts`.
- `answer_callback_query`: `fail_with` → raise; `callback_answers.append((callback_query_id, text))`.
- `get_file`: `fail_with` → raise; нет в `files` → `TelegramError("getFile", 400, "Bad Request: invalid file_id")`;
  иначе `TelegramFile(file_id, f"voice/{file_id}.oga", len(files[file_id]))`.
- `download_file`: `fail_with` → raise; `file_id = file_path.removeprefix("voice/").removesuffix(".oga")`;
  `len(data) > max_bytes` → `FileTooLarge("downloadFile", None, "file too large")`; вернуть данные.
- `set_webhook`: `webhooks.append((url, secret_token, tuple(allowed_updates)))`.

### 5. `adapters/stt/protocol.py`, `openai_compat.py`, `fake.py`

```python
class SttError(Exception):
    """Распознавание не удалось. Сообщение без ключа, URL с секретами и текста аудио."""


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, *, filename: str, mime_type: str) -> str:
        """Возвращает непустой распознанный текст (strip). Иначе — SttError."""
```

```python
class OpenAiCompatibleStt:
    """OpenAI-совместимый POST <api_url>/audio/transcriptions (D-05)."""

    def __init__(
        self, api_url: str, api_key: str, model: str, http: httpx.AsyncClient, *, timeout_sec: float = 120.0
    ) -> None
    def __repr__(self) -> str            # "OpenAiCompatibleStt(model=…)" — без ключа
```

`transcribe`: `url = api_url.rstrip("/") + "/audio/transcriptions"`;
`http.post(url, headers={"Authorization": f"Bearer {api_key}"}, data={"model": model, "response_format": "json"},
files={"file": (filename, audio, mime_type)}, timeout=httpx.Timeout(timeout_sec, connect=10.0))`.
`language` не передаётся (автоопределение). Ошибки:
`httpx.HTTPError` → `SttError(f"stt request failed: {type(exc).__name__}") from None`;
`status_code != 200` → `SttError(f"stt http {status_code}")`; не JSON / нет строкового `text` →
`SttError("stt invalid response")`; `text.strip() == ""` → `SttError("stt empty transcription")`.

```python
class FakeSpeechToText:
    def __init__(self, text: str = "распознанный текст", *, error: SttError | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[int, str, str]] = []  # (len(audio), filename, mime_type)
```
`transcribe`: запись в `calls`; `error` → raise; `text.strip() == ""` → `SttError("stt empty transcription")`;
вернуть `text.strip()`.

### 6. `security/redaction.py`

```python
REDACTED = "[REDACTED]"
_MIN_EXTRA_VALUE_LENGTH = 8
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"), REDACTED),  # токен Telegram-бота
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"), REDACTED),  # GitLab PAT
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), REDACTED),  # Anthropic
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), rf"\1 {REDACTED}"),
)


def redact(text: str, extra_values: Iterable[str] = ()) -> str:
    """Заменяет точные значения extra_values (длиной ≥ 8, сначала длинные) и шаблоны токенов на [REDACTED]."""
```

Порядок: сначала точные значения (`sorted(set(v for v in extra_values if len(v) >= 8), key=len, reverse=True)`,
`str.replace`), затем шаблоны (`pattern.sub(replacement, text)`). Модуль дополняется в `mvp-09`.

### 7. `telegram/parse.py`

Внутренние модели Telegram (`model_config = ConfigDict(extra="ignore")`), имена с `_`:
`_Chat(id: int)`, `_Voice(file_id: str, file_unique_id: str, duration: int, mime_type: str | None = None,
file_size: int | None = None)`, `_Message(message_id: int, chat: _Chat, text: str | None = None,
voice: _Voice | None = None)`, `_CallbackQuery(id: str, data: str | None = None, message: _Message | None = None)`,
`_Update(update_id: int, message: _Message | None = None, callback_query: _CallbackQuery | None = None)`.

Результат (`model_config = ConfigDict(frozen=True, extra="forbid")`):

```python
UpdateKind = Literal["update", "callback"]


class IncomingText(BaseModel):
    type: Literal["text"] = "text"
    update_id: int
    chat_id: int
    message_id: int
    text: str


class IncomingVoice(BaseModel):
    type: Literal["voice"] = "voice"
    update_id: int
    chat_id: int
    message_id: int
    file_id: str
    duration: int
    mime_type: str | None = None
    file_size: int | None = None


class ButtonPress(BaseModel):
    type: Literal["button"] = "button"
    update_id: int
    callback_query_id: str
    chat_id: int
    message_id: int
    data: str


Incoming = Annotated[IncomingText | IncomingVoice | ButtonPress, Field(discriminator="type")]
_INCOMING: TypeAdapter[Incoming] = TypeAdapter(Incoming)


def parse_update(raw: object) -> Incoming | None
def dump_incoming(incoming: Incoming) -> dict[str, Any]       # incoming.model_dump(mode="json")
def load_incoming(payload: object) -> Incoming | None         # None, если payload None или невалиден
def dedup_key(incoming: Incoming) -> tuple[UpdateKind, str]
```

`parse_update`:
1. `_Update.model_validate(raw)`; `ValidationError` → `None`.
2. Есть `callback_query`: `data is None` или `message is None` или `len(id) > 64` → `None`; иначе
   `ButtonPress(update_id, callback_query_id=cq.id, chat_id=cq.message.chat.id, message_id=cq.message.message_id,
   data=cq.data)`.
3. Нет `message` → `None` (`edited_message`, `channel_post` и прочее не обрабатываются).
4. Есть `voice` → `IncomingVoice(...)`.
5. Есть `text`: `stripped = text.strip()`; пустой или `stripped.startswith("/")` → `None`; иначе
   `IncomingText(..., text=stripped)`.
6. Иначе (стикер, фото, документ) → `None`.

`dedup_key`: `ButtonPress` → `("callback", callback_query_id)`; иначе → `("update", str(update_id))`.

### 8. `telegram/render.py`

```python
STAGE_CHOOSING: Final = "выберите проект"
TEXT_STT_FAILED: Final = "не удалось распознать, пришлите текстом"
TEXT_ALREADY_CHOSEN: Final = "проект уже выбран"
TEXT_UNKNOWN_PROJECT: Final = "проект не найден"
TEXT_TASK_NOT_FOUND: Final = "задача не найдена"
TEXT_BAD_BUTTON: Final = "кнопка устарела"
CALLBACK_PREFIX: Final = "ws"
MAX_CALLBACK_BYTES: Final = 64
MAX_MESSAGE_LEN: Final = 4096
SHORT_TITLE_LEN: Final = 40
CARD_TEXT_LEN: Final = 1000


def planning_stage(workspace_name: str) -> str        # f"проект «{workspace_name}», планирование"
def short_title(text: str) -> str
def stage_line(title: str, stage: str) -> str          # f"Задача [{title}] ({stage})"
def render_card(text: str, lines: Sequence[str]) -> str
def build_callback_data(task_id: UUID, workspace_id: str) -> str
def parse_callback_data(data: str) -> tuple[UUID, str] | None
def workspace_keyboard(task_id: UUID, workspaces: Sequence[WorkspaceConfig]) -> InlineKeyboard
```

- `short_title` («краткое название»): первая непустая строка текста, пробелы схлопнуты `" ".join(line.split())`;
  если длина ≤ 40 — как есть; иначе `collapsed[:39].rstrip() + "…"`. Пустой текст → `""`.
- `render_card`: `body = text.strip()`; если `len(body) > 1000` → `body[:999].rstrip() + "…"`;
  `result = "\n".join([body, "", *lines])`; если `len(result) > 4096` → `result[:4095] + "…"`.
- `build_callback_data`: `data = f"ws:{task_id.hex}:{workspace_id}"`; `len(data.encode()) > 64` →
  `ValueError("callback_data длиннее 64 байт")`.
- `parse_callback_data`: `parts = data.split(":", 2)`; нужно `len(parts) == 3`, `parts[0] == "ws"`,
  `len(parts[1]) == 32`, `UUID(hex=parts[1])` без `ValueError`, `parts[2] != ""`; иначе `None`.
- `workspace_keyboard`: `InlineKeyboard(rows=tuple((InlineButton(text=w.name,
  callback_data=build_callback_data(task_id, w.id)),) for w in workspaces))`.

Пример карточки после выбора проекта:

```
добавь экспорт в CSV

Задача [добавь экспорт в CSV] (выберите проект)
Задача [добавь экспорт в CSV] (проект «Магазин», планирование)
```

### 9. `services/context.py`

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class BotContext:
    """Зависимости сервисов бота: сессии, адаптеры, workspace и владелец. Собирается в wiring.py."""

    session_factory: async_sessionmaker[AsyncSession]
    telegram: TelegramClient
    stt: SpeechToText | None
    workspaces: tuple[WorkspaceConfig, ...]
    owner_chat_id: int
    secret_values: tuple[str, ...]
    voice_max_bytes: int

    @property
    def known_workspace_ids(self) -> tuple[str, ...]: ...
```

Сервисы `intake` и `notify` — оркестрирующие: первым аргументом принимают `ctx: BotContext`, а не сессию, и
открывают короткие сессии `async with ctx.session_factory() as session:` на каждый шаг, потому что между шагами
идут сетевые вызовы (STT, Telegram). Каждый шаг с записью — одна транзакция с commit (D-24).

### 10. `services/tasks.py` — новая функция

```python
async def select_workspace(
    session: AsyncSession,
    task_id: UUID,
    workspace_id: str,
    *,
    known_workspace_ids: Collection[str],
    source: TaskEventSource,
    text: str | None = None,
) -> Task:
    """Назначает workspace и переводит задачу choosing → planning одной транзакцией.

    Бросает UnknownWorkspace, NotFound, InvalidTransition (задача уже не в choosing) — до записи.
    """
```

Реализация: `workspace_id not in known_workspace_ids` → `UnknownWorkspace`; `select(Task).where(Task.id == task_id)
.with_for_update().execution_options(populate_existing=True)`; `None` → `NotFound("task", task_id)`;
`ensure_transition(task.kind, task.status, TaskStatus.PLANNING)`; `task.workspace_id = workspace_id`;
`task.status = TaskStatus.PLANNING`; `TaskEvent(task_id, status=PLANNING, text=text, source=source)`;
`await _commit(session, task, event)`; лог `task workspace selected id=%s workspace=%s`.

### 11. `services/notify.py`

```python
async def send_task_card(ctx: BotContext, task: Task) -> None
async def append_stage(ctx: BotContext, task_id: UUID, stage: str) -> None
async def reply(ctx: BotContext, text: str) -> None
```

- `send_task_card` — идемпотентна: если `session.get(TelegramMessage, task.id)` не `None` → `return`.
  Иначе `source = redact(task.text, ctx.secret_values)` (до `short_title` и усечения, S4), `line = stage_line(short_title(source), STAGE_CHOOSING)`;
  `text = redact(render_card(source, [line]), ctx.secret_values)`;
  `message_id = await ctx.telegram.send_message(ctx.owner_chat_id, text, reply_markup=workspace_keyboard(task.id,
  ctx.workspaces))` (`TelegramError` пробрасывается вызывающему); затем в новой сессии
  `TelegramMessage(task_id=task.id, chat_id=ctx.owner_chat_id, message_id=message_id, lines=[line])` + commit.
- `append_stage`: в одной сессии: `task = await get_task(session, task_id)` (`NotFound` пробрасывается);
  `line = stage_line(short_title(task.text), stage)`; `card = select(TelegramMessage).where(task_id == …)
  .with_for_update()`.
  - `card is None`: `text = redact(render_card(source, [line]), …)`, где `source` — текст задачи после `redact` (как в `send_task_card`); `send_message(ctx.owner_chat_id, text)`
    (без клавиатуры); `TelegramError` → лог warning, `rollback`, `return`; иначе добавить `TelegramMessage` с
    `lines=[line]`, commit.
  - иначе `lines = [*card.lines, line]`; `text = redact(render_card(source, lines), …)`;
    `edit_message_text(card.chat_id, card.message_id, text)` (без `reply_markup` — клавиатура убирается);
    `MessageNotEditable` → `card.message_id = await send_message(card.chat_id, text)` (её `TelegramError` →
    warning); прочая `TelegramError` → warning. В любом из этих случаев `card.lines = lines` (новый список:
    JSONB без `MutableList` не видит изменения на месте) и commit.
- `reply`: `send_message(ctx.owner_chat_id, redact(text, ctx.secret_values))`; `TelegramError` → warning.

Логи: `logger.warning("telegram %s failed task=%s: %s", exc.method, task_id, type(exc).__name__)` — без текста.

### 12. `services/intake.py`

```python
STALE_AFTER: Final = timedelta(minutes=1)
PAYLOAD_TTL: Final = timedelta(hours=24)  # необработанный апдейт старше этого срока списывается (S2a)
MAX_TASK_TEXT: Final = 20_000


async def record_incoming(session: AsyncSession, incoming: Incoming) -> bool
async def process_recorded(ctx: BotContext, kind: str, external_id: str) -> None
async def choose_workspace(ctx: BotContext, press: ButtonPress) -> None
async def recover_pending(ctx: BotContext, *, stale_after: timedelta = STALE_AFTER) -> int
async def _transcribe(ctx: BotContext, voice: IncomingVoice) -> str | None
async def _create_choosing_task(ctx: BotContext, text: str) -> Task
async def _answer(ctx: BotContext, callback_query_id: str, text: str | None) -> None
```

**`record_incoming`** — `kind, external_id = dedup_key(incoming)`;
`stmt = postgresql.insert(TelegramUpdate).values(kind=kind, external_id=external_id,
payload=dump_incoming(incoming)).on_conflict_do_nothing(index_elements=["kind", "external_id"])
.returning(TelegramUpdate.external_id)`; `inserted = (await session.execute(stmt)).scalar_one_or_none()`;
`await session.commit()`; вернуть `inserted is not None`. `rowcount` не использовать.

**`process_recorded`** — обёртка: `try: await _process_locked(ctx, kind, external_id)`
`except Exception as exc: logger.error("telegram update failed kind=%s id=%s: %s", kind, external_id,
type(exc).__name__)` (без трассировки). Никогда не бросает: это фоновая задача webhook.

**`_process_locked`**:
1. `async with ctx.session_factory() as lock_session:` `row = select(TelegramUpdate).where(kind == …,
   external_id == …, processed_at.is_(None)).with_for_update(skip_locked=True)` → `scalar_one_or_none()`.
   `None` → `return` (обработан или обрабатывается).
2. `incoming = load_incoming(row.payload)`; `created: Task | None = None`; `stt_failed = False`.
   - `incoming is None` → `logger.warning("telegram update without payload kind=%s id=%s", …)`.
   - `ButtonPress` → `await choose_workspace(ctx, incoming)`.
   - `IncomingText` → `created = await _create_choosing_task(ctx, incoming.text)`.
   - `IncomingVoice` → `text = await _transcribe(ctx, incoming)`; `None` → `stt_failed = True`, иначе
     `created = await _create_choosing_task(ctx, text)`.
3. `row.processed_at = datetime.now(UTC)`; `row.payload = None`; `await lock_session.commit()`.
4. После выхода из `lock_session`: `stt_failed` → `await reply(ctx, TEXT_STT_FAILED)`;
   `created is not None` → `try: await send_task_card(ctx, created) except TelegramError as exc:` warning
   (карточку досылает `recover_pending`).

**`_create_choosing_task`** — в одной сессии: `create_task(session, kind=TaskKind.PLAN, text=text[:MAX_TASK_TEXT],
source=TaskSource.TELEGRAM, known_workspace_ids=ctx.known_workspace_ids)`, затем
`change_status(session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.TELEGRAM)`; вернуть результат
`change_status`.

**`_transcribe`** — возвращает `None` при любой неудаче (каждая — `logger.warning` с причиной без текста):
`ctx.stt is None` («stt not configured»); `voice.file_size` задан и `> ctx.voice_max_bytes`;
`file = await ctx.telegram.get_file(voice.file_id)`; `file.file_path is None`; `file.file_size` задан и больше лимита;
`audio = await ctx.telegram.download_file(file.file_path, max_bytes=ctx.voice_max_bytes)`;
`text = await ctx.stt.transcribe(audio, filename="voice.ogg", mime_type=voice.mime_type or "audio/ogg")`;
`(TelegramError, SttError)` → `None`. Успех → `text.strip()[:MAX_TASK_TEXT]` или `None`, если пусто.

**`choose_workspace`**:
1. `parsed = parse_callback_data(press.data)`; `None` → `_answer(ctx, id, TEXT_BAD_BUTTON)`, `return`.
2. `task_id, workspace_id = parsed`; `workspace = next((w for w in ctx.workspaces if w.id == workspace_id), None)`;
   `None` → `_answer(…, TEXT_UNKNOWN_PROJECT)`, `return`.
3. В сессии `task = await select_workspace(session, task_id, workspace_id, known_workspace_ids=…,
   source=TaskEventSource.TELEGRAM)`: `NotFound` → `_answer(…, TEXT_TASK_NOT_FOUND)`, `return`;
   `InvalidTransition` → `_answer(…, TEXT_ALREADY_CHOSEN)`, `return`.
4. `await _answer(ctx, press.callback_query_id, None)` (убирает «часики» у кнопки);
   `await append_stage(ctx, task.id, planning_stage(workspace.name))`.

**`_answer`** — `answer_callback_query(callback_query_id, text=text)`; `TelegramError` → warning (ответ на старый
callback после рестарта Telegram отклоняет — это не ошибка обработки).

**`recover_pending`**:
1. `threshold = datetime.now(UTC) - stale_after`; `expired_before = datetime.now(UTC) - PAYLOAD_TTL`. Строки с
   `received_at < expired_before` списываются одним UPDATE (`processed_at = now`, `payload = NULL`, условие
   `processed_at IS NULL`) без `process_recorded`; остальные обрабатываются через `process_recorded`. Возвращается
   число апдейтов, обработанных или списанных. TTL `PAYLOAD_TTL` (24 ч) проверяется только здесь, при старте worker;
   периодической очистки необработанных апдейтов нет (ревью цикл 2, C3).
2. Сессия: `keys = select(TelegramUpdate.kind, TelegramUpdate.external_id).where(processed_at.is_(None),
   received_at < threshold).order_by(TelegramUpdate.received_at)` → `.all()`.
3. `for kind, external_id in keys: await process_recorded(ctx, kind, external_id)`.
4. Сессия: `orphans = select(Task).outerjoin(TelegramMessage, TelegramMessage.task_id == Task.id).where(
   Task.source == TaskSource.TELEGRAM, Task.status.in_([TaskStatus.NEW, TaskStatus.CHOOSING]),
   Task.created_at < threshold, TelegramMessage.task_id.is_(None)).order_by(Task.created_at)` → список.
5. Для каждой: `try:` если `status == NEW` → `task = change_status(…, CHOOSING, source=TELEGRAM)` (своя сессия);
   `await send_task_card(ctx, task)`; `except (TelegramError, DomainError) as exc:` warning.
6. `logger.info("telegram recovery updates=%d cards=%d", …)`; вернуть `len(keys)`.

### 13. `services/webhook.py`

```python
WEBHOOK_PATH: Final = "/telegram/webhook"
ALLOWED_UPDATES: Final = ("message", "callback_query")


def webhook_url(public_url: str | None) -> str
async def register_webhook(telegram: TelegramClient, url: str, secret_token: str) -> None
```

`webhook_url`: не задан/пустой → `ValueError("не задан")`; `urlsplit`: `scheme != "https"` или пустой `netloc` →
`ValueError("нужен адрес https://")`; `"@" in netloc` → `ValueError("адрес не должен содержать учётные данные")`;
`query` или `fragment` непусты → `ValueError("адрес не должен содержать query или fragment")` (S6);
вернуть `public_url.rstrip("/") + WEBHOOK_PATH`. `register_webhook` вызывает
`telegram.set_webhook(url, secret_token=secret_token, allowed_updates=ALLOWED_UPDATES)`.

### 14. `api/deps.py` — дополнения

```python
async def require_webhook_secret(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> None:
    """401 {"detail": "unauthorized"} без заголовка или при несовпадении. Сравнение sha256 + compare_digest."""


def get_bot_context(request: Request) -> BotContext      # request.app.state.bot


BotContextDep = Annotated[BotContext, Depends(get_bot_context)]
```
`expected = request.app.state.settings.telegram_webhook_secret` (`SecretStr`). Заголовок `WWW-Authenticate` не
ставится. Общий хелпер `_unauthorized()` не меняется (для webhook — `HTTPException(status_code=401,
detail="unauthorized")`).

### 15. `api/telegram_webhook.py`

```python
router = APIRouter(tags=["telegram"], dependencies=[Depends(require_webhook_secret)])


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request, background_tasks: BackgroundTasks, session: SessionDep, bot: BotContextDep
) -> dict[str, bool]:
```
1. `raw: object = await request.json()`; `ValueError` → `{"ok": True}`.
2. `incoming = parse_update(raw)`; `None` или `incoming.chat_id != bot.owner_chat_id` → `{"ok": True}` (ничего не
   пишется и не отправляется).
3. `if await record_incoming(session, incoming):` `kind, external_id = dedup_key(incoming)`;
   `background_tasks.add_task(process_recorded, bot, kind, external_id)`.
4. Вернуть `{"ok": True}` (статус 200).

Секрет проверяется router-зависимостью раньше тела (как `/tasks`).

### 16. `wiring.py`

```python
@dataclass(frozen=True, slots=True)
class BotAdapters:
    telegram: TelegramClient
    stt: SpeechToText | None


def build_http_client() -> httpx.AsyncClient            # httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
def build_adapters(settings: Settings, http: httpx.AsyncClient) -> BotAdapters
def secret_values(settings: Settings) -> tuple[str, ...]
def build_bot_context(
    settings: Settings,
    config: HarnessConfig,
    session_factory: async_sessionmaker[AsyncSession],
    adapters: BotAdapters,
) -> BotContext
```
- `build_adapters`: `HttpxTelegramClient(settings.telegram_bot_token.get_secret_value(), http)`; STT —
  `OpenAiCompatibleStt(stt_api_url, stt_api_key.get_secret_value(), stt_model, http)`, только если заданы все три
  (`stt_api_url`, `stt_api_key`, `stt_model`), иначе `None`.
- `secret_values`: для каждого имени из `Settings.model_fields` значение `getattr(settings, name)`; если это
  `SecretStr` — добавить `get_secret_value()`; вернуть кортеж.
- `build_bot_context`: `owner_chat_id=int(settings.telegram_chat_id)`, `workspaces=tuple(config.workspaces)`,
  `voice_max_bytes=settings.voice_max_bytes`.

### 17. `app.py`

`create_app(settings: Settings, config: HarnessConfig, *, adapters: BotAdapters | None = None) -> FastAPI`.
В lifespan после фабрики сессий: `http = build_http_client()`;
`bot_adapters = adapters if adapters is not None else build_adapters(settings, http)`;
`app.state.bot = build_bot_context(settings, config, app.state.session_factory, bot_adapters)`; в `finally` —
`await http.aclose()` перед `engine.dispose()`. `app.include_router(telegram_router)` после `tasks_router`.

### 18. `worker.py`

```python
async def start_worker(
    settings: Settings, config: HarnessConfig, stop: asyncio.Event, *, adapters: BotAdapters | None = None
) -> None
async def serve_worker(settings: Settings, config: HarnessConfig) -> None
```
`start_worker`: `engine = create_engine(settings.database_url.get_secret_value())`; `factory`; `http =
build_http_client()`; `try:` `bot = build_bot_context(settings, config, factory, adapters if adapters is not None
else build_adapters(settings, http))`; `try: await recover_pending(bot) except Exception as exc:
logger.warning("telegram recovery failed: %s", type(exc).__name__)`; `await run_worker(
settings.worker_poll_interval_sec, stop)`; `finally: await http.aclose(); await engine.dispose()`.
`serve_worker`: `stop`, обработчики сигналов (как сейчас), затем `await start_worker(settings, config, stop)`.
`run_worker` не меняется (лог `worker started` остаётся в нём). `cli.py::worker`: `settings, config =
_load_or_exit()` и `asyncio.run(serve_worker(settings, config))`.

### 19. `cli.py`

- `_configure_logging()`: после `basicConfig` — `logging.getLogger("httpx").setLevel(logging.WARNING)` и
  `logging.getLogger("httpcore").setLevel(logging.WARNING)` с комментарием «в URL Telegram — токен бота».
- `from harness_server import wiring` (модуль, не имена: тест подменяет `wiring.build_adapters`).
- Группа: `telegram_app = typer.Typer(help="Telegram: регистрация webhook.", no_args_is_help=True)`;
  `app.add_typer(telegram_app, name="telegram")`.
- Команда `@telegram_app.command("set-webhook") def set_webhook() -> None`:
  `settings, _ = _load_or_exit()`; `_configure_logging()`;
  `url = webhook_url(settings.harness_public_url)`, `ValueError as exc` →
  `typer.echo(f"Ошибка конфигурации: HARNESS_PUBLIC_URL: {exc}", err=True)`, `Exit(1)`;
  `asyncio.run(_set_webhook(settings, url))`, `TelegramError as exc` → `typer.echo(f"Ошибка Telegram: {exc}",
  err=True)`, `Exit(1)`; успех → `typer.echo(f"webhook установлен: {url}")`.
- `async def _set_webhook(settings: Settings, url: str) -> None`: `async with wiring.build_http_client() as http:`
  `adapters = wiring.build_adapters(settings, http)`;
  `await register_webhook(adapters.telegram, url, settings.telegram_webhook_secret.get_secret_value())`.

### 20. `settings.py`

- `_WEBHOOK_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")` остаётся; добавить `_WEBHOOK_SECRET_MIN_LENGTH = 32`;
  `_check_webhook_secret_format`: regex не совпал **или** длина < 32 → `ValueError("допустимы только латиница,
  цифры, _ и -, длина от 32 до 256 (openssl rand -hex 32)")`.
- `_CHAT_ID_RE = re.compile(r"\d+")`; валидатор `_check_chat_id` для `telegram_chat_id`: не `fullmatch` или
  `int(value) <= 0` → `ValueError("должен быть положительным числовым id личного чата владельца (групповые чаты не
  поддерживаются, D-30)")`. Значение в текст ошибки не выводится (D-30, S1).
- `stt_api_url`: валидатор `_check_stt_api_url` — только `https://` (`urlsplit(value).scheme == "https"`), иначе
  `ValueError("должен начинаться с https://")` (S6).
- `stt_provider: Literal["openai"] | None = None` (комментарий: «OpenAI-совместимый протокол; Whisper через Polza»).
- `voice_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0, le=20 * 1024 * 1024)` (комментарий: «лимит
  getFile Telegram; ENV VOICE_MAX_BYTES»).

### 21. `config.py`

`WorkspaceConfig.id: str = Field(min_length=1, max_length=28, pattern=r"^[A-Za-z0-9_-]+$")` с комментарием:
«id входит в callback_data `ws:<task hex>:<id>` ≤ 64 байт (D-28)».

### 22. Схема и миграция `0002`

`db/models/telegram.py::TelegramUpdate` — новое поле (после `processed_at`):
```python
# Нормализованный апдейт владельца до обработки; обнуляется после неё (D-27).
# none_as_null=True: None пишется SQL NULL, а не JSON 'null' (ревью цикл 2, C1).
payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
```
Докстринг класса дополнить: «payload хранится только до обработки». Файл
`db/migrations/versions/20261018_0002_telegram_update_payload.py`:

```python
"""telegram_updates.payload: нормализованный апдейт владельца до обработки (D-27)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_updates",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_updates", "payload")
```
Миграция не импортирует `harness_server`. Именованных ограничений нет, поэтому `op.f` не нужен. Индекса не
добавляется (строк мало, выборка восстановления — раз при старте).

## Data flow / control flow

1. **Текст.** Telegram → webhook: секрет ✓ → `parse_update` → `IncomingText` (чат владельца) → `record_incoming`
   → `True` → фон `process_recorded("update", "<update_id>")` → замок строки → `create_task(plan, new)` →
   `change_status(choosing)` → `processed_at`, `payload = NULL`, commit → `send_task_card` (текст задачи + строка
   `Задача [<название>] (выберите проект)` + кнопки) → `telegram_messages`.
2. **Голос.** Как текст, но перед созданием задачи `_transcribe`: `get_file` → `download_file` (≤ лимита) →
   `stt.transcribe`. Неудача → отметка обработанным → `reply("не удалось распознать, пришлите текстом")`.
3. **Кнопка.** `ButtonPress` → `record_incoming` с ключом `("callback", callback_query.id)` → фон →
   `choose_workspace` → `select_workspace` (`planning`, workspace, событие) → `answer_callback_query` →
   `append_stage(«проект «<name>», планирование»)` → `editMessageText` без клавиатуры.
4. **Повторная доставка** того же `update_id` / `callback_query.id` → `record_incoming` → `False` → фон не ставится.
5. **Рестарт.** Webhook записал апдейт, процесс упал → строка `processed_at IS NULL` с `payload` → при старте worker
   `recover_pending` через ≥ 1 мин обрабатывает её тем же `process_recorded`.

## Validation and error handling

| Ситуация | Результат |
|---|---|
| Нет/неверный `X-Telegram-Bot-Api-Secret-Token` | `401 {"detail":"unauthorized"}`, тело не читается, БД не меняется |
| Тело не JSON | `200 {"ok": true}`, ничего не пишется |
| Апдейт не поддерживается (`edited_message`, стикер, `/start`, callback без data) | `200`, ничего не пишется |
| Чужой `chat_id` | `200`, ничего не пишется и не отправляется |
| Дубль `update_id` / `callback_query.id` | `200`, фон не ставится |
| STT не настроен / ошибка / пустой текст / файл > `VOICE_MAX_BYTES` | `reply(TEXT_STT_FAILED)`, задачи нет |
| Ошибка Telegram при отправке карточки | warning; задача в `choosing`; карточку досылает `recover_pending` |
| `callback_data` не разбирается | `answer_callback_query("кнопка устарела")` |
| Workspace из кнопки нет в конфиге | `answer_callback_query("проект не найден")` |
| Задачи из кнопки нет | `answer_callback_query("задача не найдена")` |
| Задача не в `choosing` | `answer_callback_query("проект уже выбран")`, без изменений и событий |
| `editMessageText`: «not modified» | успех |
| `editMessageText`: сообщение недоступно | новое сообщение, `telegram_messages.message_id` обновлён |
| Исключение в фоне | `logger.error` с именем класса; строка остаётся необработанной до восстановления |
| `TELEGRAM_WEBHOOK_SECRET` < 32 символов, `TELEGRAM_CHAT_ID` не число, `STT_PROVIDER` ≠ `openai`, `VOICE_MAX_BYTES` вне (0, 20 МиБ] | `SettingsError`, сервер и worker не стартуют |
| `workspaces[].id` длиннее 28 или с символами вне `A-Za-z0-9_-` | `ConfigError` |
| `HARNESS_PUBLIC_URL` не задан / не https | `set-webhook` → код 1, «Ошибка конфигурации: HARNESS_PUBLIC_URL: …» |

## Authorization and security

- Подпись webhook — `X-Telegram-Bot-Api-Secret-Token`, сравнение `hmac.compare_digest` sha256-дайджестов;
  секрет ≥ 32 символов. Владелец — `chat_id == TELEGRAM_CHAT_ID` для сообщений и для callback (чат сообщения
  с кнопкой). Чужой чат не получает ответа и не оставляет следов в БД (C6).
- Токен бота — в URL Bot API: `TelegramError` без URL и без текста исключения httpx; логгеры `httpx`/`httpcore` —
  WARNING; `__repr__` адаптеров без секретов. Ключ STT — только в заголовке.
- Текст в Telegram — через `redact` с точными значениями всех `SecretStr` настроек и шаблонами токенов.
- Минимизация: `payload` — нормализованная модель без `from`/имён, обнуляется после обработки; логи без текста
  задачи и без трассировок.
- SQL — только ORM/Core с параметрами (`insert().on_conflict_do_nothing()`), без конкатенации.
- `callback_data` от клиента не доверенный: формат проверяется, workspace сверяется с конфигом, задача — с БД,
  переход — с таблицей статусов.

## Backward compatibility

- `create_app(settings, config)` и существующие тесты `/tasks` работают без изменений (`adapters` — keyword с
  `None`). Lifespan теперь строит `HttpxTelegramClient` — сетевых вызовов при старте нет.
- `serve_worker` меняет сигнатуру (единственный вызов — `cli.py::worker`). `test_worker.py` с недоступной БД
  продолжает проходить: ошибка восстановления логируется, затем пишется `worker started`.
- Ужесточение ENV/конфига: короткий `TELEGRAM_WEBHOOK_SECRET`, нечисловой `TELEGRAM_CHAT_ID`, длинный или с
  точкой/двоеточием `workspaces[].id` — сервер не стартует с понятной ошибкой. Прод ещё не развёрнут (MVP).
- Миграция `0002` аддитивная (nullable-колонка).

## Test strategy

Все async-тесты на БД начинаются с `pytestmark = pytest.mark.asyncio(loop_scope="session")`. Сервисы — с
`committed_session_factory` (реальные коммиты: сервисы открывают свои сессии) и фейковыми адаптерами. HTTP — как
`test_tasks_api.py::_app_client`: `monkeypatch.setenv("DATABASE_URL", migrated_database_url)`, `load_settings()`,
`create_app(settings, load_config(...), adapters=BotAdapters(fake_telegram, fake_stt))`, `LifespanManager` +
`httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`. `ASGITransport` дожидается
завершения приложения вместе с `BackgroundTasks`; каждый HTTP-тест после запроса **явно** проверяет состояние БД и
фейка (не полагается на неявное ожидание и не использует `sleep`).

### Фикстуры

`apps/server/tests/conftest.py`:
- в `ALL_ENV_NAMES` добавить `"VOICE_MAX_BYTES"`;
- в `valid_env` `TELEGRAM_WEBHOOK_SECRET` заменить на `"test-webhook-secret-0123456789abcdef"` (36 символов,
  тестовое значение), если текущее короче 32;
- фикстура `telegram_update` → `Callable[[str], dict[str, Any]]`: читает
  `Path(__file__).parent / "fixtures" / "telegram" / f"{name}.json"` (`json.loads`), возвращает новый dict;
- фикстура `make_bot_context` → `Callable[..., BotContext]` с параметрами
  `(factory, *, telegram, stt=None, workspaces=None, voice_max_bytes=20 * 1024 * 1024)`; по умолчанию workspaces —
  `(WorkspaceConfig(id="demo", name="Демо-проект", voice_aliases=[], gitlab_project="group/demo"),
  WorkspaceConfig(id="shop", name="Магазин", voice_aliases=[], gitlab_project="group/shop"))`, `owner_chat_id=424242`,
  `secret_values=("test-webhook-secret-0123456789abcdef",)`.

`apps/server/tests/fixtures/telegram/` (записанные апдейты в формате Bot API, chat id владельца `424242`):
- `text_message.json`: `{"update_id": 10001, "message": {"message_id": 501, "from": {"id": 424242, "is_bot": false,
  "first_name": "Owner"}, "chat": {"id": 424242, "type": "private"}, "date": 1760000000,
  "text": "добавь экспорт в CSV"}}`
- `voice_message.json`: `update_id` 10002, `message_id` 502, тот же `from`/`chat`, `"voice": {"file_id": "VOICE_FILE_1",
  "file_unique_id": "VOICE_UNIQUE_1", "duration": 3, "mime_type": "audio/ogg", "file_size": 2048}`
- `callback_query.json`: `{"update_id": 10003, "callback_query": {"id": "4242000000000000001", "from": {…},
  "chat_instance": "-100500", "message": {"message_id": 100, "chat": {"id": 424242, "type": "private"},
  "date": 1760000001, "text": "добавь экспорт в CSV"}, "data": "ws:00000000000000000000000000000000:demo"}}`
  (тесты подменяют `data` и при необходимости `id`)
- `foreign_chat_message.json`: как `text_message`, `update_id` 10004, `chat.id` и `from.id` = `999`, текст «чужое»
- `edited_message.json`: `{"update_id": 10005, "edited_message": {…как message…}}`
- `start_command.json`: как `text_message`, `update_id` 10006, `"text": "/start"`

### Тесты (имена обязательны)

- `test_telegram_client.py` (respx, `HttpxTelegramClient("123456:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz0123", http)`):
  `test_send_message_posts_json_and_returns_message_id`; `test_send_message_serializes_inline_keyboard`;
  `test_api_error_raises_telegram_error_without_token` (`ok:false, 400` → `TelegramError`, токена нет в `str(exc)`,
  `repr(exc)`, `repr(client)`); `test_network_error_does_not_leak_token` (`side_effect=httpx.ConnectError(...)`);
  `test_edit_not_modified_is_ignored`; `test_edit_not_editable_raises_message_not_editable` (parametrize:
  `"Bad Request: message can't be edited"`, `"Bad Request: message to edit not found"`,
  `"Bad Request: MESSAGE_ID_INVALID"`); `test_edit_other_error_is_raised`; `test_answer_callback_query`;
  `test_get_file_returns_path_and_size`; `test_download_file_uses_file_url`; `test_download_file_over_limit_raises`;
  `test_download_file_rejects_path_traversal`; `test_set_webhook_sends_secret_and_allowed_updates`.
- `test_stt_client.py` (respx, `respx.utils.decode_data(request)` для multipart): `test_transcribe_sends_multipart`
  (model, `response_format=json`, имя файла `voice.ogg`, `Authorization: Bearer …`, URL `…/audio/transcriptions` при
  `api_url` со слешем на конце); `test_transcribe_returns_stripped_text`; `test_transcribe_empty_text_raises`;
  `test_transcribe_http_error_raises_without_key` (500 → `SttError`, ключа нет в `str(exc)`);
  `test_transcribe_timeout_raises` (`side_effect=httpx.ReadTimeout`); `test_transcribe_invalid_json_raises`.
- `test_redaction.py`: `test_redacts_telegram_token`, `test_redacts_gitlab_token`, `test_redacts_anthropic_key`,
  `test_redacts_bearer_keeps_scheme`, `test_redacts_extra_values`, `test_short_extra_values_ignored`,
  `test_text_without_secrets_unchanged`.
- `test_telegram_parse.py`: `test_parse_text_message`, `test_parse_voice_message`, `test_parse_callback_query`,
  `test_parse_foreign_chat_keeps_chat_id` (парсер не фильтрует, фильтрует webhook),
  `test_unsupported_updates_return_none` (parametrize: `edited_message`, `start_command`, `{}`, `"not a dict"`,
  callback без `data`), `test_dump_and_load_roundtrip` (для всех трёх типов), `test_load_incoming_invalid_returns_none`
  (`None`, `{"type": "x"}`), `test_dedup_key` (`("update","10001")`, `("callback","4242000000000000001")`),
  `test_payload_has_no_sender_fields` (`dump_incoming(...)` без ключей `from`, `first_name`).
- `test_telegram_render.py`: `test_short_title_keeps_short_text`, `test_short_title_truncates_to_40`,
  `test_short_title_uses_first_non_empty_line`, `test_stage_line_format` (`Задача [добавь экспорт] (выберите проект)`),
  `test_callback_data_roundtrip`, `test_callback_data_max_length_ok` (workspace id 28 символов → 64 байта),
  `test_callback_data_too_long_raises` (29 символов), `test_parse_callback_data_rejects_garbage` (parametrize:
  `"ws:abc:demo"`, `"xx:<hex>:demo"`, `"ws:<hex>:"`, `"ws"`), `test_render_card_limits_length`,
  `test_workspace_keyboard_one_button_per_workspace`.
- `test_telegram_webhook.py` (HTTP + `committed_session_factory` для проверок):
  `test_wrong_secret_returns_401` (сценарий «Неверный секрет»: 401, `telegram_updates` и `tasks` пусты, фейк без
  вызовов); `test_missing_secret_returns_401`; `test_foreign_chat_ignored` (сценарий «Чужой чат»: 200, нет строк,
  нет задач, `fake.sent == []`); `test_unsupported_update_not_recorded` (`start_command`); `test_invalid_json_returns_200`;
  `test_text_creates_choosing_task_with_buttons` (задача `plan`/`choosing`/`telegram`, одна карточка с кнопкой
  «Демо-проект», `telegram_messages` с `lines == ["Задача [добавь экспорт в CSV] (выберите проект)"]`);
  `test_duplicate_delivery_creates_one_task` (сценарий «Повторная доставка»: тот же JSON дважды → 1 задача,
  1 карточка); `test_payload_cleared_after_processing` (`processed_at` не `None`, `payload is None`);
  `test_button_press_selects_workspace` (`planning`, `workspace_id == "demo"`, `callback_answers == [(id, None)]`,
  правка карточки без клавиатуры, последняя строка `(проект «Демо-проект», планирование)`);
  `test_duplicate_callback_processed_once` (тот же `callback_query.id`, разные `update_id` → одно событие
  `planning`, один ответ).
- `test_intake_service.py` (`make_bot_context`, фейки): `test_voice_creates_task_with_transcript` (сценарий
  «Голосовая задача»: `FakeSpeechToText("создай страницу контактов")`, `files={"VOICE_FILE_1": b"OggS…"}` → задача с
  этим текстом, карточка содержит текст, вызов STT `(…, "voice.ogg", "audio/ogg")`);
  `test_stt_error_replies_and_creates_no_task` (сценарий «Провайдер недоступен»: `error=SttError("stt http 500")` →
  0 задач, `fake.sent[0].text == "не удалось распознать, пришлите текстом"`); `test_stt_empty_text_replies`;
  `test_stt_not_configured_replies` (`stt=None`); `test_voice_over_limit_replies` (`voice_max_bytes=1024`,
  `file_size=2048`, STT не вызывался); `test_choose_workspace_sets_planning` (сценарий «Выбор workspace»: «Магазин» →
  `workspace_id == "shop"`, `planning`, строка этапа `(проект «Магазин», планирование)` в тексте правки);
  `test_repeat_press_after_choice` (сценарий «Повторное нажатие»: нажатие «Демо-проект» после «Магазин» →
  `workspace_id == "shop"`, ответ `"проект уже выбран"`, событий `planning` — 1);
  `test_unknown_workspace_button` (`"проект не найден"`); `test_garbage_callback` (`"кнопка устарела"`);
  `test_missing_task_button` (`"задача не найдена"`); `test_process_recorded_twice_creates_one_task`;
  `test_card_send_failure_keeps_task_without_duplicate` (`fail_with` при отправке → задача в `choosing`, апдейт
  обработан, повторный `process_recorded` не создаёт вторую задачу).
- `test_notify_service.py`: `test_two_stages_single_message` (сценарий «Два этапа»: задача с карточкой,
  `append_stage(…, "начата")`, `append_stage(…, "готова, MR создан")` → `len(fake.sent) == 1`, `len(fake.edits) == 2`,
  итоговый текст содержит обе строки по формату); `test_not_editable_falls_back_to_new_message` (`not_editable` →
  новое сообщение, `message_id` в БД обновлён); `test_append_stage_without_card_sends_message`;
  `test_append_stage_redacts_secrets` (задача с текстом, содержащим значение из `secret_values` → в отправленном
  тексте `[REDACTED]`); `test_other_telegram_error_keeps_lines` (`fail_with` → строки сохранены в БД);
  `test_send_task_card_is_idempotent`.
- `test_recovery.py`: `test_recover_processes_stale_update` (строка с `payload` текста и
  `received_at = now() - 2 мин` → задача создана, строка обработана); `test_recover_skips_fresh_update`
  (`received_at = now()` → не тронута); `test_recover_skips_processed_update`;
  `test_recover_marks_legacy_row_without_payload` (`payload = NULL` → `processed_at` проставлен, задач нет);
  `test_recover_sends_missing_card` (задача `telegram` в `choosing`, `created_at` старше 1 мин, без карточки →
  карточка отправлена); `test_recover_moves_new_task_to_choosing`. Строки вставлять через
  `postgresql.insert(TelegramUpdate)` с явным `received_at`; `created_at` задачи — `update(Task)` после создания.
- `test_webhook_service.py`: `test_webhook_url_appends_path`, `test_webhook_url_requires_https` (parametrize:
  `None`, `""`, `"http://x"`, `"https://user:pw@x"`), `test_register_webhook_passes_allowed_updates`.
- `test_task_service.py` (дописать, `db_session`): `test_select_workspace_moves_to_planning`,
  `test_select_workspace_twice_rejected` (`InvalidTransition`, workspace не изменился),
  `test_select_workspace_unknown_workspace`, `test_select_workspace_missing_task`.
- `test_settings.py` (дописать/изменить): `test_webhook_secret_accepts_telegram_alphabet` — значение
  `"Abc_123-xyz" * 3`; `test_webhook_secret_too_short_rejected` (1 символ); `test_webhook_secret_32_chars_accepted`;
  `test_chat_id_must_be_numeric` (`"abc"` → `SettingsError` с `TELEGRAM_CHAT_ID`), `test_negative_chat_id_accepted`
  (`"-1001234567890"`); `test_stt_provider_unknown_rejected` (`"whisper-local"`); `test_voice_max_bytes_default`;
  `test_voice_max_bytes_over_limit_rejected` (`20971521`).
- `test_config.py` (дописать): `test_workspace_id_too_long_rejected` (29 символов), `test_workspace_id_with_colon_rejected`
  (`"a:b"`), `test_workspace_id_28_chars_accepted`.
- `test_cli.py` (дописать): `test_help_lists_commands` — добавить `"telegram"` в список;
  `test_telegram_set_webhook_uses_public_url` (`HARNESS_PUBLIC_URL=https://harness.example.com/`, monkeypatch
  `harness_server.wiring.build_adapters` → `BotAdapters(fake, None)`; код 0;
  `fake.webhooks == [("https://harness.example.com/telegram/webhook", <секрет из valid_env>, ("message",
  "callback_query"))]`; секрета нет в `result.output`); `test_set_webhook_requires_public_url` (код 1, текст
  `HARNESS_PUBLIC_URL`); `test_set_webhook_reports_telegram_error` (фейк с `fail_with` → код 1, «Ошибка Telegram»);
  `test_configure_logging_silences_httpx` (после `_configure_logging()` уровень `httpx` и `httpcore` ≥ WARNING).
- `test_migrations.py` (дописать): `test_telegram_updates_payload_column` (после `upgrade head`: колонка `payload`
  есть, `nullable`, тип JSONB — через `sqlalchemy.inspect` на синхронном соединении `run_sync`).
- `test_worker.py` (дописать, async, `pytestmark` не ставить на весь модуль — существующий тест синхронный;
  декоратор `@pytest.mark.asyncio(loop_scope="session")` на новом тесте):
  `test_start_worker_runs_recovery` (строка апдейта старше 2 мин в БД; `valid_env` + `DATABASE_URL` =
  `migrated_database_url`; `stop` уже установлен; `start_worker(settings, config, stop,
  adapters=BotAdapters(fake, None))` → строка обработана, задача создана).
- `test_telegram_live.py` (`pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]`):
  `test_live_send_and_edit_message` — переменные `LIVE_TELEGRAM_BOT_TOKEN`, `LIVE_TELEGRAM_CHAT_ID` (не входят в
  `ALL_ENV_NAMES`, поэтому `clean_env` их не удаляет); нет переменных → `pytest.skip`. Отправляет сообщение,
  редактирует, повторяет ту же правку (не должно быть исключения). По умолчанию не запускается
  (`addopts = -m 'not live'`).

## Acceptance criteria

1. `uv run ruff format . && ./tools/harness check` зелёный; все тесты из списка существуют и проходят; нет
   `type: ignore` без комментария причины.
2. `openspec validate mvp-04-telegram-intake --strict` и `openspec validate --all` без ошибок.
3. `alembic check` после `upgrade head` без расхождений; `downgrade base` → `upgrade head` проходит (существующий
   `test_downgrade_and_upgrade_roundtrip`).
4. Все сценарии `specs/telegram-bot/spec.md` и `specs/speech-to-text/spec.md` покрыты тестами (имена выше).
5. `api/telegram_webhook.py` не импортирует `sqlalchemy` и `harness_server.db`; `services/*` не импортируют `httpx`;
   `adapters/*` не импортируют `harness_server.db`, `services`, `domain`; `telegram/*` не импортирует `db`, `services`.
6. В логах и исключениях нет токена бота и ключа STT (тесты `*_without_token`, `*_without_key`,
   `test_configure_logging_silences_httpx`).
7. Документация обновлена (задача 4.2), project-memory синхронизирована (5.1).
8. Задача 4.3 (ручная live-проверка) остаётся открытой до проверки пользователем — это не блокирует ревью.

## Rollback

- Код: revert коммитов изменения.
- БД: `uv run alembic downgrade 0001` удаляет `telegram_updates.payload` (необработанные апдейты теряют тело; перед
  откатом дождаться `processed_at` у всех строк).
- Telegram: `deleteWebhook` вручную (Bot API) или повторный `set-webhook` на старый адрес.
- Ужесточения settings/config откатываются вместе с кодом.

## Разрешённые для изменения файлы

Новые: все из таблицы «Новые файлы». Изменяемые:
`apps/server/src/harness_server/{settings,config,app,cli,worker}.py`, `api/deps.py`, `services/tasks.py`,
`db/models/telegram.py`; `apps/server/tests/{conftest,test_settings,test_config,test_cli,test_task_service,
test_migrations,test_worker}.py`; `ARCHITECTURE.md` (§2, §3, §5, §8, §9), `docs/deployment.md`, `apps/server/README.md`,
`db/README.md` (строка про `0002`), `docker-compose.yml` (одна строка `VOICE_MAX_BYTES: ${VOICE_MAX_BYTES:-}` в
сервисах `server` и `worker` рядом с `WORKER_POLL_INTERVAL_SEC`), `PLAN.md` (статус mvp-04), `.env.example`
(только строки `VOICE_MAX_BYTES` и комментарий про длину `TELEGRAM_WEBHOOK_SECRET`; **только по явному разрешению
пользователя через оркестратора**), `openspec/changes/mvp-04-telegram-intake/tasks.md` (отметки `[x]`).
Не трогать: `api/health.py`, `api/tasks.py`, `domain/*`, `db/base.py`, `db/session.py`,
`db/migrations/versions/20261018_0001_initial.py`, `db/migrations/env.py`, `shared/*`, `pyproject.toml` (оба),
`uv.lock`, `Dockerfile`, `docs/decisions.md` (уже обновлён Architect), остальные OpenSpec-изменения.

## Risks / Trade-offs

- [Фоновая задача потеряется при рестарте] → `payload` + `processed_at`; `recover_pending` при старте worker
  (апдейты старше 1 мин). Пока worker не перезапущен, апдейт ждёт; периодическое восстановление — `health-alerts`
  или `mvp-06` (цикл worker).
- [Сбой между `create_task` и отметкой апдейта] → два коротких commit без сетевых вызовов между ними; при падении
  процесса ровно в этом окне восстановление создаст вторую задачу. Принято для MVP; исключить можно ссылкой
  апдейт → задача (отдельное изменение).
- [OGG/Opus не в официальном списке форматов OpenAI `/audio/transcriptions`] → mvp-04 отправляет файл как есть
  (`voice.ogg`, `audio/ogg`); Whisper через Polza может принять или отклонить. Отказ провайдера даёт ответ
  «не удалось распознать, пришлите текстом» (без потери данных). Проверяется в 4.3; конвертация — `voice-robustness`.
- [Строка-замок держит транзакцию во время STT (до ~2 мин)] → один апдейт = одно соединение пула сверх рабочей
  сессии; в MVP один владелец и редкие сообщения.
- [`editMessageText` без `reply_markup` убирает клавиатуру] → поведение Bot API; проверяется в 4.3.
- [Тексты ошибок Telegram для недоступного сообщения не подтверждены дословно] → проверка по `error_code == 400`
  и подстрокам; неизвестный текст → warning, строки сохранены, следующая правка повторит попытку.
- [Ограничение `workspaces[].id` ≤ 28 и `A-Za-z0-9_-`] → существующий `harness.yaml` с длинным id перестанет
  загружаться с понятной ошибкой; в примере — `demo`.
