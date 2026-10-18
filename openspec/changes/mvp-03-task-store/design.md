# Design: mvp-03-task-store

Документ — исполняемая спецификация для Implementer. Имена файлов, символов, сигнатур и тестов обязательны.
Если что-то из написанного невозможно (ошибка mypy/Alembic, которую нельзя устранить без отступления от
текста), Implementer останавливается и сообщает, а не придумывает замену.

## Context: текущее состояние (mvp-02, проверено по коду)

- `harness_server/app.py::create_app(settings, config)` — lifespan создаёт `AsyncEngine`
  (`pool_pre_ping=True`) в `app.state.engine`, кладёт `app.state.settings`, `app.state.config`; OpenAPI/Swagger
  выключены; подключён только `api/health.py`.
- `settings.py::Settings` — `harness_admin_token: SecretStr | None = None` уже объявлен, проверки длины нет;
  `_SECRET_KEY_MIN_LENGTH = 32` и валидатор `_check_secret_key_length` для `harness_secret_key`;
  `load_settings()` переводит `ValidationError` в `SettingsError` без значений.
- `config.py` — `_SECRET_SEGMENTS = {"token","key","password","secret","apikey"}`, `_reject_secret_fields`
  рекурсивно до Pydantic; `GitLabConfig.base_url: str` без проверки формата; `_format_errors` без input.
- `db/migrations/env.py` — async engine (`NullPool`), URL из `DATABASE_URL`, `asyncio.run` внутри
  `run_migrations_online`, `target_metadata = None`, `fileConfig(config.config_file_name)` (глушит логгеры).
  `alembic.ini` в корне: `script_location = %(here)s/db/migrations`,
  `file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s`. `db/migrations/versions/` пуст.
- `cli.py::migrate` вызывает `alembic_command.upgrade(AlembicConfig("alembic.ini"), "head")` в том же процессе.
- `worker.py` — цикл без очереди (не меняется в mvp-03).
- `tests/conftest.py` — autouse `clean_env`, `valid_env`, session-фикстура `database_url`
  (`TEST_DATABASE_URL` или `PostgresContainer("postgres:16-alpine", driver="asyncpg")`).
- `pyproject.toml` — `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "session"`, ruff
  `E,F,I,B,UP,SIM,ASYNC,RUF`, line-length 100, mypy strict (`mypy apps shared`).
- `apps/server/pyproject.toml` уже содержит `sqlalchemy[asyncio]>=2.0.30` (greenlet ставится), `asyncpg`,
  `alembic`. Версии в lock: sqlalchemy 2.1.5, asyncpg 0.32.0, fastapi 0.143.3, pydantic 2.14.1,
  alembic 1.20.0, pytest-asyncio 1.4.0, testcontainers 4.15.0. Postgres — `postgres:16-alpine`.
- `docker-compose.yml` уже передаёт `HARNESS_ADMIN_TOKEN`; Compose не меняется.
- `harness_shared` содержит только `health.py`; модели внешнего мира живут в `shared/src/harness_shared/`.

## Goals / Non-Goals

**Goals:** одна функция смены статуса для всех входов; очередь без гонок; каждая смена статуса видна в ленте;
схема 9 таблиц MVP; `POST/GET /tasks` с fail-closed авторизацией.

**Non-Goals:** см. proposal.md («Не входит»).

## Decisions

Каждое решение — с отвергнутой альтернативой. Номера D-NN — в docs/decisions.md.

1. **Машина статусов в `domain/statuses.py`** — словарь `kind → {from → frozenset(to)}`; сервис вызывает
   `ensure_transition()` до записи. Отвергнуто: переходы CHECK/триггером в БД — сложно менять, нет понятной ошибки.
2. **Значения перечислений в БД — `VARCHAR(16)` + именованный CHECK** (D-22). В ORM —
   `sa.Enum(..., native_enum=False, create_constraint=False, length=16, validate_strings=True,
   values_callable=...)`, CHECK объявляется явно в `__table_args__` через `enum_check()`. В миграции значения
   записаны литералами (миграция не импортирует код приложения). Отвергнуто: нативный `ENUM` Postgres —
   `ADD VALUE` вне транзакции, нет `DROP VALUE`, autogenerate не видит изменения; `create_constraint=True` —
   неявное имя ограничения, которое трудно повторить в ручной миграции.
3. **UUIDv7 — собственный генератор `db/ids.py::uuid7()`** по RFC 9562 с монотонным 12-битным счётчиком внутри
   миллисекунды (D-21). Отвергнуто: `uuid-utils` (новая нативная зависимость, типизация под mypy strict не
   проверена); `uuid.uuid7` есть только в Python 3.14; `uuidv7()` есть только в Postgres 18.
4. **Каждая публичная функция сервиса — одна единица работы и сама делает `await session.commit()`** (D-24).
   Вызывающий открывает сессию (`async with session_factory() as session`) и не коммитит. При исключении
   изменения не коммитятся (закрытие сессии откатывает). Отвергнуто: коммит во входах (`api`, `mcp`) —
   бизнес-правило «статус + событие атомарно» утекло бы из `services`.
5. **Очередь** (D-24): `claim_next_task` = `SELECT … WHERE kind = :kind AND status = :from ORDER BY priority DESC,
   created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED` + переход `from → to` + событие + commit. Брокера нет (D-08).
   Отвергнуто: advisory locks — сложнее, не дают порядка.
6. **Смена статуса блокирует строку** `SELECT … FOR UPDATE` (без SKIP LOCKED), чтобы два параллельных
   `change_status` не потеряли переход. Отвергнуто: оптимистичная версия строки — лишняя колонка и повторы.
7. **Временный `HARNESS_ADMIN_TOKEN`** (D-23): `HTTPBearer(auto_error=False)` + собственная проверка;
   `401 {"detail":"unauthorized"}` и `WWW-Authenticate: Bearer` для отсутствующего заголовка, другой схемы,
   неверного токена и **не заданного** `HARNESS_ADMIN_TOKEN` (fail-closed). Сравнение
   `hmac.compare_digest(sha256(given), sha256(expected))` на байтах. Длина ≥ 32 проверяется в `settings.py`
   (перенос из `console-auth` 4.1). Отвергнуто: `HTTPBearer()` по умолчанию — 403/401 в зависимости от версии
   FastAPI и без проверки неверного токена; 503 при не заданном токене — раскрывает конфигурацию.
8. **`POST /tasks` создаёт задачу `plan` в `new` с источником `api`** (D-25). `TaskSource` получает значение
   `api`; источник события — отдельный enum `TaskEventSource`. Создание задачи событие не пишет: лента —
   это смены статуса и отчёты. Отвергнуто: создавать `implement` в `backlog` — обходит планирование (ТЗ §5).
9. **Все 9 таблиц MVP — в `0001`** (D-26), включая `telegram_updates.processed_at` (нужен mvp-04) и составной PK
   `telegram_updates (kind, external_id)`. Отвергнуто: таблица на каждое изменение — больше миграций при
   известной схеме.
10. **Цикл FK `tasks.spec_item_id ↔ spec_items.plan_task_id`** разрывается: в ORM `use_alter=True` на
    `tasks.spec_item_id`, в миграции этот FK создаётся `op.create_foreign_key` после всех таблиц.
11. **Без ORM `relationship()`**: события читаются явным запросом. Отвергнуто: relationship с lazy load —
    `MissingGreenlet` в async.
12. **Хвосты mvp-02** (D-26): `fileConfig(..., disable_existing_loggers=False)`; сегменты секретов расширены;
    `gitlab.base_url` без userinfo.

## Файлы и символы

### Новые файлы

| Путь | Содержимое |
|---|---|
| `shared/src/harness_shared/tasks.py` | `TaskKind`, `TaskStatus`, `TaskSource`, `TaskEventSource`, `TestsState`, `TaskCreateIn`, `TaskOut`, `TaskEventOut`, `TaskDetailOut` |
| `shared/src/harness_shared/sandboxes.py` | `SandboxStatus`, `AgentRole` |
| `apps/server/src/harness_server/domain/__init__.py` | docstring пакета |
| `apps/server/src/harness_server/domain/errors.py` | `DomainError`, `InvalidTransition`, `InvalidStatus`, `UnsupportedKind`, `UnknownWorkspace`, `NotFound`, `Forbidden` |
| `apps/server/src/harness_server/domain/statuses.py` | `TRANSITIONS`, `INITIAL_STATUS`, `TERMINAL_STATUSES`, `parse_status`, `initial_status`, `allowed_transitions`, `ensure_transition` |
| `apps/server/src/harness_server/db/__init__.py` | docstring пакета |
| `apps/server/src/harness_server/db/ids.py` | `uuid7()` |
| `apps/server/src/harness_server/db/base.py` | `NAMING_CONVENTION`, `Base`, `enum_type()`, `enum_check()`, `TimestampMixin` |
| `apps/server/src/harness_server/db/session.py` | `create_engine()`, `create_session_factory()` |
| `apps/server/src/harness_server/db/models/__init__.py` | реэкспорт всех моделей (регистрирует таблицы в `Base.metadata`) |
| `apps/server/src/harness_server/db/models/tasks.py` | `Task`, `TaskEvent` |
| `apps/server/src/harness_server/db/models/planning.py` | `Routing`, `SpecItem`, `Checkpoint` |
| `apps/server/src/harness_server/db/models/sandboxes.py` | `Sandbox`, `TaskToken` |
| `apps/server/src/harness_server/db/models/telegram.py` | `TelegramMessage`, `TelegramUpdate` |
| `apps/server/src/harness_server/services/__init__.py` | docstring пакета |
| `apps/server/src/harness_server/services/tasks.py` | функции сервиса задач |
| `apps/server/src/harness_server/api/deps.py` | `get_session`, `get_config`, `require_admin_token`, `SessionDep`, `ConfigDep` |
| `apps/server/src/harness_server/api/tasks.py` | `router`, `create_task_endpoint`, `get_task_endpoint` |
| `db/migrations/versions/20261018_0001_initial.py` | ревизия `0001` |
| `apps/server/tests/test_ids.py`, `test_statuses.py`, `test_migrations.py`, `test_task_service.py`, `test_task_queue.py`, `test_tasks_api.py` | тесты |

### Изменяемые файлы

`apps/server/src/harness_server/app.py`, `settings.py`, `config.py`; `db/migrations/env.py`;
`apps/server/tests/conftest.py`, `test_settings.py`, `test_config.py`; документация (см. «Разрешённые файлы»).

## Proposed architecture

```
api/tasks.py ──Depends──► api/deps.py (require_admin_token, get_session, get_config)
     │
     ▼
services/tasks.py ──► domain/statuses.py, domain/errors.py   (без I/O)
     │
     ▼
db/models/*.py ──► db/base.py (Base, enum_type, enum_check), db/ids.py (uuid7)
     ▲
db/migrations/env.py: target_metadata = Base.metadata (импорт harness_server.db.models)

shared/harness_shared/tasks.py — enums и DTO, импортируются domain, db, services, api
```

Правила: `api` не делает запросов к БД, только вызывает `services`. `domain` не импортирует `sqlalchemy`.
`db/models` не импортирует `services` и `api`.

## Detailed specification

### 1. `shared/src/harness_shared/tasks.py`

Все enum — `enum.StrEnum`, имена членов — значение в верхнем регистре (`NEW = "new"`). Порядок членов —
как ниже (он же порядок значений в CHECK).

- `TaskKind`: `plan`, `implement`, `check`.
- `TaskStatus`: `new`, `choosing`, `planning`, `backlog`, `active`, `testing`, `ready`, `merged`, `error`,
  `stalled`, `paused`, `trash`.
- `TaskSource`: `telegram`, `spec`, `mcp`, `api`.
- `TaskEventSource`: `telegram`, `agent`, `worker`, `api`.
- `TestsState`: `not_run`, `passed`, `failed`, `no_tests`.

DTO (Pydantic v2):

```python
TaskText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
WorkspaceId = Annotated[str, StringConstraints(min_length=1, max_length=64)]

class TaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: TaskText
    workspace_id: WorkspaceId | None = None

class TaskEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID; task_id: UUID; status: TaskStatus; text: str | None
    source: TaskEventSource; created_at: datetime

class TaskOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID; kind: TaskKind; workspace_id: str | None; parent_id: UUID | None; text: str
    status: TaskStatus; priority: int; source: TaskSource; spec_item_id: UUID | None
    branch: str | None; mr_url: str | None; result: str | None; tests_state: TestsState
    created_at: datetime; updated_at: datetime

class TaskDetailOut(TaskOut):
    events: list[TaskEventOut]
```

`shared/src/harness_shared/sandboxes.py`: `SandboxStatus` (`paused`, `active`, `error`), `AgentRole`
(`planner`, `implementer`).

### 2. `domain/errors.py`

```python
class DomainError(Exception):
    """Базовая ошибка домена. code — машинный код для API/MCP; message без секретов."""
    code: ClassVar[str] = "domain_error"

class InvalidTransition(DomainError):   code = "invalid_transition"
    def __init__(self, kind: TaskKind, from_status: TaskStatus, to_status: TaskStatus) -> None
        # message: f"переход {from_status} → {to_status} недопустим для {kind}"; атрибуты kind/from_status/to_status
class InvalidStatus(DomainError):       code = "invalid_status"
    def __init__(self, value: str) -> None   # message: f"неизвестный статус: {value!r}"
class UnsupportedKind(DomainError):     code = "unsupported_kind"
    def __init__(self, kind: TaskKind) -> None
class UnknownWorkspace(DomainError):    code = "unknown_workspace"
    def __init__(self, workspace_id: str) -> None
class NotFound(DomainError):            code = "not_found"
    def __init__(self, entity: str, entity_id: object) -> None
class Forbidden(DomainError):           code = "forbidden"
```

`Forbidden` в mvp-03 не используется сервисом (нужен mvp-07), но объявляется и проверяется тестом
`test_domain_error_codes`.

### 3. `domain/statuses.py`

```python
TRANSITIONS: Final[Mapping[TaskKind, Mapping[TaskStatus, frozenset[TaskStatus]]]] = {
    TaskKind.PLAN: {
        NEW: {CHOOSING}, CHOOSING: {PLANNING, TRASH}, PLANNING: {READY, ERROR},
    },
    TaskKind.IMPLEMENT: {
        BACKLOG: {ACTIVE}, ACTIVE: {TESTING, ERROR}, TESTING: {READY, ERROR},
        READY: {MERGED}, ERROR: {BACKLOG},
    },
}
INITIAL_STATUS: Final[Mapping[TaskKind, TaskStatus]] = {PLAN: NEW, IMPLEMENT: BACKLOG}
TERMINAL_STATUSES: Final[Mapping[TaskKind, frozenset[TaskStatus]]] = {
    PLAN: {READY, ERROR, TRASH}, IMPLEMENT: {MERGED},
}
def parse_status(value: TaskStatus | str) -> TaskStatus      # не из enum → InvalidStatus
def initial_status(kind: TaskKind) -> TaskStatus             # нет в INITIAL_STATUS → UnsupportedKind
def allowed_transitions(kind: TaskKind, from_status: TaskStatus) -> frozenset[TaskStatus]
    # kind нет в TRANSITIONS → UnsupportedKind; from_status нет → frozenset()
def ensure_transition(kind: TaskKind, from_status: TaskStatus, to_status: TaskStatus) -> None
    # to_status не в allowed_transitions → InvalidTransition
```

(В коде — полные имена `TaskStatus.NEW` и т.д., значения множеств — `frozenset`.) Kind `check` в таблицах
отсутствует намеренно.

### 4. `db/ids.py`

```python
_lock = threading.Lock()
_last_ms = 0
_last_seq = 0
_SEQ_MAX = 0xFFF

def uuid7() -> uuid.UUID:
    """UUIDv7 (RFC 9562): 48 бит unix-мс, версия 7, 12 бит счётчика, вариант 10, 62 бита случайных.

    Внутри процесса значения строго возрастают: в той же миллисекунде (или при откате часов) счётчик
    увеличивается, при переполнении счётчика метка времени сдвигается на 1 мс вперёд.
    """
    global _last_ms, _last_seq
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms > _last_ms:
            _last_ms = now_ms
            # Старший бит счётчика оставляем нулём, чтобы в этой мс было место для увеличений.
            _last_seq = int.from_bytes(os.urandom(2)) & 0x7FF
        else:
            _last_seq += 1
            if _last_seq > _SEQ_MAX:
                _last_ms += 1
                _last_seq = 0
        ms, seq = _last_ms, _last_seq
    rand_b = int.from_bytes(os.urandom(8)) & ((1 << 62) - 1)
    return uuid.UUID(int=(ms << 80) | (0x7 << 76) | (seq << 64) | (0b10 << 62) | rand_b)
```

### 5. `db/base.py`

```python
NAMING_CONVENTION: Final = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

def enum_type(enum_cls: type[StrEnum]) -> sa.Enum:
    """VARCHAR(16) со значениями enum (не именами). CHECK объявляется отдельно через enum_check (D-22)."""
    return sa.Enum(enum_cls, native_enum=False, create_constraint=False, length=16,
                   validate_strings=True, values_callable=lambda cls: [m.value for m in cls])

def enum_check(column: str, enum_cls: type[StrEnum]) -> sa.CheckConstraint:
    """CHECK column IN (...) с именем ck_<table>_<column>. Значения — константы enum, не ввод."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return sa.CheckConstraint(f"{column} IN ({values})", name=column)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Все таблицы имеют `id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)`,
кроме `telegram_messages` (PK `task_id`) и `telegram_updates` (PK `kind, external_id`). Колонки с
`server_default=func.now()` — `nullable=False`. Индексы и UNIQUE объявляются **явными именами** в
`__table_args__` (не `index=True`).

### 6. Схема таблиц (ORM и миграция совпадают)

Обозначения: NN — `nullable=False`; FK → `таблица.id`; `ts` — `DateTime(timezone=True)`; `uuid` —
`Uuid(as_uuid=True)`; `enum(X)` — `enum_type(X)` в ORM и `sa.String(16)` в миграции + CHECK.

**`tasks`** (`TimestampMixin`)

| Колонка | Тип | Ограничения |
|---|---|---|
| id | uuid | PK, default `uuid7` |
| kind | enum(TaskKind) | NN, CHECK `ck_tasks_kind` |
| workspace_id | String(64) | NULL |
| parent_id | uuid | NULL, FK tasks ON DELETE SET NULL |
| text | Text | NN |
| status | enum(TaskStatus) | NN, CHECK `ck_tasks_status` |
| priority | Integer | NN, `server_default="0"`, ORM `default=0` |
| source | enum(TaskSource) | NN, CHECK `ck_tasks_source` |
| spec_item_id | uuid | NULL, FK spec_items ON DELETE SET NULL, `use_alter=True` |
| branch | String(255) | NULL |
| mr_url | Text | NULL |
| result | Text | NULL |
| tests_state | enum(TestsState) | NN, `server_default="not_run"`, ORM `default=TestsState.NOT_RUN`, CHECK `ck_tasks_tests_state` |
| created_at, updated_at | ts | NN, server_default now() |

Индексы: `ix_tasks_queue (kind, status, priority, created_at)`, `ix_tasks_workspace_id (workspace_id)`,
`ix_tasks_parent_id (parent_id)`.

**`task_events`**: id uuid PK; task_id uuid NN FK tasks ON DELETE CASCADE; status enum(TaskStatus) NN
(`ck_task_events_status`); text Text NULL; source enum(TaskEventSource) NN (`ck_task_events_source`);
created_at ts NN now(). Индекс `ix_task_events_task_id_created_at (task_id, created_at)`.

**`routings`**: id uuid PK; task_id uuid NN FK tasks CASCADE; command_class String(32) NN; options JSONB NN
`server_default=sa.text("'[]'::jsonb")`, `Mapped[list[dict[str, Any]]]`, ORM `default=list`;
chosen_workspace_id String(64) NULL; raw_response Text NULL; confidence Float NULL; created_at ts NN now().
Индекс `ix_routings_task_id (task_id)`.

**`checkpoints`**: id uuid PK; task_id uuid NN FK tasks CASCADE; summary Text NN; files JSONB NN
`'[]'::jsonb`, `Mapped[list[str]]`, ORM `default=list`; diff_redacted Text NULL; next_step Text NULL;
status String(32) NN; tokens Integer NULL; created_at ts NN now(). Индекс `ix_checkpoints_task_id (task_id)`.

**`spec_items`** (`TimestampMixin`): id uuid PK; workspace_id String(64) NN; plan_task_id uuid NULL FK tasks
SET NULL; change_id String(128) NN; key String(64) NN; text Text NN; status String(32) NN (значения задаёт
mvp-08, CHECK нет); last_checkpoint_id uuid NULL FK checkpoints SET NULL. UNIQUE
`uq_spec_items_workspace_change_key (workspace_id, change_id, key)`.

**`sandboxes`** (`TimestampMixin`): id uuid PK; provider_id String(128) NN; agent_type String(32) NN;
status enum(SandboxStatus) NN (`ck_sandboxes_status`); current_task_id uuid NULL FK tasks SET NULL;
profile_version String(64) NULL. UNIQUE `uq_sandboxes_provider_id (provider_id)`.

**`task_tokens`**: id uuid PK; task_id uuid NN FK tasks CASCADE; token_hash String(128) NN; role
enum(AgentRole) NN (`ck_task_tokens_role`); expires_at ts NN; revoked_at ts NULL; created_at ts NN now().
UNIQUE `uq_task_tokens_token_hash (token_hash)`; индекс `ix_task_tokens_task_id (task_id)`.
Значение токена не хранится — только хеш (mvp-06).

**`telegram_messages`**: task_id uuid PK FK tasks CASCADE; chat_id BigInteger NN; message_id BigInteger NN;
lines JSONB NN `'[]'::jsonb`, `Mapped[list[str]]`, ORM `default=list`; created_at, updated_at (`TimestampMixin`).

**`telegram_updates`**: kind String(16) NN PK, CHECK `ck_telegram_updates_kind`: `kind IN ('update',
'callback')` (в ORM — `sa.CheckConstraint("kind IN ('update', 'callback')", name="kind")`, колонка
`String(16)`, без enum); external_id String(64) NN PK; received_at ts NN now(); processed_at ts NULL.

Имена FK — по convention, например `fk_tasks_parent_id_tasks`, `fk_tasks_spec_item_id_spec_items`,
`fk_task_events_task_id_tasks`. PK — `pk_<table>`.

### 7. Миграция `db/migrations/versions/20261018_0001_initial.py`

- `revision = "0001"`, `down_revision = None`, `branch_labels = None`, `depends_on = None`; docstring
  `"""initial: таблицы MVP (ARCHITECTURE.md §3)."""`.
- Пишется **вручную** по таблице выше, без импорта `harness_server`/`harness_shared`. Значения CHECK —
  литералы в том же порядке, что члены enum. Имена ограничений — через `op.f("…")` с полным именем.
- `upgrade()` — порядок `create_table`: `tasks` (без FK на spec_items), `task_events`, `routings`,
  `checkpoints`, `spec_items`, `sandboxes`, `task_tokens`, `telegram_messages`, `telegram_updates`; затем
  `op.create_index(...)` для каждого индекса; последним —
  `op.create_foreign_key(op.f("fk_tasks_spec_item_id_spec_items"), "tasks", "spec_items", ["spec_item_id"],
  ["id"], ondelete="SET NULL")`.
- `downgrade()` — `op.drop_constraint(op.f("fk_tasks_spec_item_id_spec_items"), "tasks", type_="foreignkey")`,
  затем `op.drop_table` в обратном порядке (индексы удаляются вместе с таблицами).
- Проверка: `alembic check` без расхождений (тест `test_alembic_check_reports_no_diff`). Если `alembic check`
  сообщает `modify_type` для колонок `enum_type` (String vs Enum) — **остановиться и сообщить**, не менять
  типы и не отключать `compare_type`.

### 8. `db/migrations/env.py`

- `fileConfig(config.config_file_name, disable_existing_loggers=False)` с комментарием «почему»: `migrate`
  выполняется в процессе приложения, иначе логгеры `harness_server.*` отключаются.
- `from harness_server.db.base import Base` и `import harness_server.db.models  # noqa: F401` (регистрация
  таблиц); `target_metadata = Base.metadata`. Обновить module docstring (модели подключены).
- Остальное не менять.

### 9. `db/session.py`

```python
def create_engine(database_url: str) -> AsyncEngine:
    """Async engine приложения; pool_pre_ping — см. комментарий в app.py (обрыв после рестарта Postgres)."""
    return create_async_engine(database_url, pool_pre_ping=True)

def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """expire_on_commit=False: объекты читаются после commit без нового запроса (нет ленивой загрузки в async)."""
    return async_sessionmaker(engine, expire_on_commit=False)
```

`app.py` lifespan: `engine = create_engine(settings.database_url.get_secret_value())`,
`app.state.session_factory = create_session_factory(engine)`; комментарий про `pool_pre_ping` переносится
в `db/session.py`. Подключить `app.include_router(tasks_router)` после health.

### 10. `services/tasks.py`

Модуль-docstring: единственное место правил задачи; каждая публичная функция коммитит свою транзакцию (D-24).
Все функции `async`, первым аргументом `session: AsyncSession`, остальные — keyword-only.

```python
async def create_task(session, *, kind: TaskKind, text: str, source: TaskSource,
                      known_workspace_ids: Collection[str], workspace_id: str | None = None,
                      parent_id: UUID | None = None, spec_item_id: UUID | None = None,
                      priority: int = 0) -> Task
```
1. `status = initial_status(kind)` (kind `check` → `UnsupportedKind`).
2. `workspace_id is not None and workspace_id not in known_workspace_ids` → `UnknownWorkspace`.
3. `parent_id` задан и `await session.get(Task, parent_id) is None` → `NotFound("task", parent_id)`.
4. `spec_item_id` задан и `await session.get(SpecItem, spec_item_id) is None` → `NotFound("spec_item", …)`.
5. `Task(...)`, `session.add`, `await session.commit()`, вернуть задачу. Событие не создаётся.

```python
async def get_task(session, task_id: UUID) -> Task                      # нет → NotFound("task", task_id)
async def list_task_events(session, task_id: UUID) -> list[TaskEvent]  # ORDER BY created_at, id
async def list_tasks(session, *, workspace_id: str | None = None,
                     statuses: Collection[TaskStatus] | None = None, limit: int = 100) -> list[Task]
    # фильтры только если заданы; ORDER BY created_at, id; LIMIT limit
async def change_status(session, task_id: UUID, to_status: TaskStatus | str, *,
                        source: TaskEventSource, text: str | None = None) -> Task
```
`change_status`: (1) `target = parse_status(to_status)` (до запроса); (2)
`select(Task).where(Task.id == task_id).with_for_update()` → нет строки → `NotFound`; (3)
`ensure_transition(task.kind, task.status, target)`; (4) `task.status = target`, `session.add(TaskEvent(
task_id=task.id, status=target, text=text, source=source))`; (5) `await session.commit()`, вернуть задачу.
При ошибке в (1)–(3) ничего не коммитится.

```python
async def add_event(session, task_id: UUID, *, text: str, source: TaskEventSource) -> TaskEvent
```
Отчёт без смены статуса: задача читается (`NotFound`), событие со `status = task.status`, commit.

```python
async def claim_next_task(session, *, kind: TaskKind, from_status: TaskStatus, to_status: TaskStatus,
                          source: TaskEventSource = TaskEventSource.WORKER,
                          text: str | None = None) -> Task | None
```
(1) `ensure_transition(kind, from_status, to_status)` до запроса; (2)
`select(Task).where(Task.kind == kind, Task.status == from_status).order_by(Task.priority.desc(),
Task.created_at, Task.id).limit(1).with_for_update(skip_locked=True)`; (3) нет строки → `await
session.commit()` (закрыть транзакцию) и вернуть `None`; (4) статус + событие + commit, вернуть задачу.
Долгая работа выполняется вызывающим после возврата, вне транзакции.

Docstring у каждой публичной функции. Логи — только id и статусы, без текста задачи.

### 11. `api/deps.py`

```python
_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(status_code=401, detail="unauthorized",
                              headers={"WWW-Authenticate": "Bearer"})

async def require_admin_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Временный операторский доступ (D-23). Fail-closed: без настроенного токена — 401."""
    expected = request.app.state.settings.harness_admin_token   # тип Settings
    if expected is None or credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    given_digest = hashlib.sha256(credentials.credentials.encode()).digest()
    expected_digest = hashlib.sha256(expected.get_secret_value().encode()).digest()
    if not hmac.compare_digest(given_digest, expected_digest):
        raise _UNAUTHORIZED

async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session

def get_config(request: Request) -> HarnessConfig: return request.app.state.config

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ConfigDep = Annotated[HarnessConfig, Depends(get_config)]
```

Создавать новый `HTTPException` в каждом вызове допустимо вместо модульной константы — на выбор, но тело и
заголовок именно такие. Токен и заголовок `Authorization` не логируются.

### 12. `api/tasks.py`

```python
router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_admin_token)])

@router.post("", status_code=201, response_model=TaskOut)
async def create_task_endpoint(body: TaskCreateIn, session: SessionDep, config: ConfigDep) -> TaskOut:
    # services.tasks.create_task(kind=PLAN, text=body.text, source=TaskSource.API,
    #   workspace_id=body.workspace_id, known_workspace_ids=[w.id for w in config.workspaces])
    # UnknownWorkspace → HTTPException(422, detail="unknown_workspace")
    # return TaskOut.model_validate(task)

@router.get("/{task_id}", response_model=TaskDetailOut)
async def get_task_endpoint(task_id: UUID, session: SessionDep) -> TaskDetailOut:
    # get_task + list_task_events; NotFound → HTTPException(404, detail="not_found")
    # TaskDetailOut(**TaskOut.model_validate(task).model_dump(), events=[TaskEventOut.model_validate(e) ...])
```

Router-зависимость `require_admin_token` решается до валидации тела и path-параметров, поэтому запрос без
токена получает 401 даже с невалидным id или телом (проверяется тестом).

### 13. `settings.py`

`_ADMIN_TOKEN_MIN_LENGTH = 32`; валидатор:

```python
@field_validator("harness_admin_token")
@classmethod
def _check_admin_token_length(cls, value: SecretStr | None) -> SecretStr | None:
    # Токен даёт полный операторский доступ к /tasks; короткий легко подобрать (D-23).
    if value is not None and len(value.get_secret_value()) < _ADMIN_TOKEN_MIN_LENGTH:
        raise ValueError(f"должна быть не короче {_ADMIN_TOKEN_MIN_LENGTH} символов (openssl rand -hex 32)")
    return value
```

### 14. `config.py`

- `_SECRET_SEGMENTS` += `"tokens", "secrets", "passwd", "pwd", "credential", "credentials"`; обновить
  module docstring (список сегментов).
- `GitLabConfig`: `@field_validator("base_url")` — `parts = urlsplit(value)`; если `parts.username is not
  None or parts.password is not None or "@" in parts.netloc` → `ValueError("адрес не должен содержать
  учётные данные (user:pass@host); токен задаётся в ENV GITLAB_TOKEN")`. Значение в текст ошибки не
  попадает (`_format_errors` уже вызывается с `include_input=False`).

## Data flow / control flow

- **POST /tasks:** `require_admin_token` → Pydantic `TaskCreateIn` (422 при пустом тексте/лишних полях) →
  `create_task(kind=plan, source=api)` → commit → 201 `TaskOut` (`status=new`, событий нет).
- **GET /tasks/{id}:** `require_admin_token` → UUID path (422) → `get_task` (404) → `list_task_events` → 200
  `TaskDetailOut`.
- **change_status (Telegram, MCP, worker в следующих изменениях):** `parse_status` → `SELECT … FOR UPDATE` →
  `ensure_transition` → UPDATE + INSERT `task_events` → COMMIT.
- **claim_next_task (worker, mvp-06):** `ensure_transition` → `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` →
  UPDATE + INSERT → COMMIT → вызывающий выполняет долгую работу вне транзакции.

## Validation and error handling

| Ситуация | Где | Результат |
|---|---|---|
| Неизвестный статус (`"completed"`) | `parse_status` | `InvalidStatus`, задача не меняется |
| Значение вне набора на уровне БД | CHECK `ck_tasks_status` | `IntegrityError` |
| Недопустимый переход | `ensure_transition` | `InvalidTransition` (`invalid_transition`) |
| kind `check` | `initial_status`/`allowed_transitions` | `UnsupportedKind` |
| Неизвестный workspace | `create_task` | `UnknownWorkspace` → HTTP 422 `unknown_workspace` |
| Нет задачи / родителя / пункта | сервис | `NotFound` → HTTP 404 `not_found` |
| Нет/неверный/не настроен токен | `require_admin_token` | 401 `unauthorized` + `WWW-Authenticate: Bearer` |
| Пустой текст, текст > 20 000, лишнее поле | `TaskCreateIn` | 422 |
| `HARNESS_ADMIN_TOKEN` < 32 символов | `Settings` | `SettingsError`, процесс не стартует, значение не выводится |
| Userinfo в `gitlab.base_url`, новые сегменты | `config.py` | `ConfigError` с путём поля, без значения |

## Authorization and security

- `/tasks` — только с `HARNESS_ADMIN_TOKEN`; не настроен → 401 всем (fail-closed). 401 не раскрывает
  существование задачи: проверка токена раньше поиска и раньше валидации id.
- Сравнение — константное по времени на sha256-дайджестах равной длины.
- Токен — `SecretStr`, в логи, ответы и ошибки не попадает. Тесты используют явно тестовое значение.
- Только ORM с параметрами. Единственный SQL-текст в приложении — CHECK-выражения из констант enum
  (`enum_check`); в тестах — параметризованный `text()` для проверки CHECK и литеральный `TRUNCATE`.
- `task_tokens` хранит только хеш. Текст задачи не логируется (может содержать персональные данные).

## Backward compatibility

- Первая миграция, данных нет. Downgrade `0001` удаляет все таблицы MVP.
- Поведение `settings`: ранее любой `HARNESS_ADMIN_TOKEN` принимался; теперь < 32 символов — ошибка старта.
  Деплоев с этой переменной ещё нет (до mvp-03 она не читалась) — риск низкий, фиксируется в D-23.
- `config.py`: harness.yaml с ключами из новых сегментов или userinfo в `base_url` теперь отклоняется.
  `config/harness.example.yaml` таких ключей не содержит.
- Публичные модели `harness_shared.health` не меняются.

## Test strategy

Тестовая БД — `database_url` из conftest. Новые фикстуры в `apps/server/tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> Iterator[str]:
    """Применяет миграции до head один раз за сессию (синхронно: env.py сам вызывает asyncio.run)."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        alembic_command.upgrade(AlembicConfig(str(REPO_ROOT / "alembic.ini")), "head")
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous
    yield database_url

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]: ...  # create_async_engine; dispose

@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия в внешней транзакции; commit сервиса → SAVEPOINT; в конце всё откатывается."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint",
                               expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()

TRUNCATE_ALL = ("TRUNCATE TABLE telegram_updates, telegram_messages, task_tokens, sandboxes, spec_items, "
                "checkpoints, routings, task_events, tasks CASCADE")

@pytest_asyncio.fixture(loop_scope="session")
async def committed_session_factory(db_engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Настоящие коммиты на отдельных соединениях (SKIP LOCKED, HTTP). После теста — TRUNCATE."""
    yield async_sessionmaker(db_engine, expire_on_commit=False)
    async with db_engine.begin() as connection:
        await connection.execute(text(TRUNCATE_ALL))
```

`clean_env` (autouse) удаляет `DATABASE_URL` в каждом тесте — это не мешает: миграции применены в
session-фикстуре до него, а тесты, которым нужна переменная, задают её через `monkeypatch`.

Каждый модуль с async-тестами на БД (`test_task_service.py`, `test_task_queue.py`, `test_tasks_api.py`)
начинается с `pytestmark = pytest.mark.asyncio(loop_scope="session")`: session-engine asyncpg привязан к
session-циклу. `test_migrations.py`, `test_ids.py`, `test_statuses.py` — синхронные, без `pytestmark`.

Тесты (имена обязательны):

- `test_ids.py`: `test_uuid7_version_and_variant` (version == 7, variant == `uuid.RFC_4122`);
  `test_uuid7_is_strictly_increasing` (10 000 значений, каждое > предыдущего);
  `test_uuid7_timestamp_is_current` (`u.int >> 80` в `[before_ms, after_ms + 5]`).
- `test_statuses.py`: `test_allowed_transitions_pass` (parametrize по всем парам из `TRANSITIONS`);
  `test_disallowed_transitions_raise` (parametrize: все пары `TaskStatus × TaskStatus` для plan/implement вне
  таблицы → `InvalidTransition`); `test_every_status_reachable_from_initial` (BFS от `INITIAL_STATUS[kind]`
  покрывает все статусы, упомянутые в `TRANSITIONS[kind]`); `test_non_terminal_statuses_have_exit` (каждый
  достижимый статус либо в `TERMINAL_STATUSES[kind]`, либо имеет непустой `allowed_transitions`, и конечные
  статусы не имеют выходов); `test_parse_status_rejects_unknown` (`"completed"` → `InvalidStatus`);
  `test_check_kind_unsupported` (`initial_status(CHECK)`, `allowed_transitions(CHECK, NEW)` → `UnsupportedKind`);
  `test_domain_error_codes` (у каждого класса из errors.py свой `code`, все — подклассы `DomainError`).
- `test_migrations.py`: `test_alembic_check_reports_no_diff` (monkeypatch `DATABASE_URL` →
  `migrated_database_url`; `alembic_command.check(cfg)` без исключения);
  `test_downgrade_and_upgrade_roundtrip` (`downgrade(cfg, "base")`, затем `upgrade(cfg, "head")`, затем снова
  `check` без исключения); `test_migrate_keeps_application_loggers_enabled` (создать
  `logging.getLogger("harness_server.probe")` до `upgrade(cfg, "head")`, после — `.disabled is False`).
- `test_task_service.py` (`db_session`): `test_create_plan_task_starts_new`;
  `test_create_implement_task_starts_backlog`; `test_create_check_task_unsupported`;
  `test_create_task_unknown_workspace`; `test_create_task_missing_parent_not_found`;
  `test_allowed_transition_writes_event` (сценарий «Допустимый переход»: plan new→choosing→planning, последнее
  событие `planning`); `test_skipping_stage_rejected` (сценарий «Пропуск этапа»: backlog→ready →
  `InvalidTransition`, после `refresh` статус `backlog`, событий 0); `test_unknown_status_rejected` (сценарий
  «Неизвестный статус»: `change_status(..., "completed")` → `InvalidStatus`, статус не изменился);
  `test_database_rejects_unknown_status` (в `async with db_session.begin_nested()`:
  `text("UPDATE tasks SET status = :status WHERE id = :id")` с `status="completed"` → `IntegrityError`);
  `test_event_history_in_order` (сценарий «История задачи»: backlog→active→testing→ready → 3 события,
  статусы `[active, testing, ready]`); `test_add_event_keeps_status`; `test_get_task_not_found`;
  `test_list_tasks_filters_by_workspace_and_status`; `test_retry_after_error` (implement
  backlog→active→error→backlog разрешён).
- `test_task_queue.py` (`committed_session_factory`): `test_claim_returns_highest_priority_then_oldest`
  (приоритеты 0, 5, 5 → порядок: первая 5, вторая 5, 0, затем `None`); `test_claim_skips_locked_task`
  (сессия A держит `select(Task).with_for_update()` в открытой транзакции → B получает `None`; A
  `rollback` → B получает задачу, статус `active`, 1 событие с `source=worker`);
  `test_two_concurrent_claims_get_one_task` (сценарий «Два воркера»: одна задача, `asyncio.gather` двух
  `claim_next_task` на разных сессиях → ровно один не `None`); `test_two_concurrent_claims_get_different_tasks`
  (две задачи → разные id); `test_claim_rejects_invalid_transition` (backlog→ready → `InvalidTransition`);
  `test_claim_ignores_other_kind_and_status`.
- `test_tasks_api.py` (`committed_session_factory`, `valid_env`, monkeypatch `DATABASE_URL` →
  `migrated_database_url`, `HARNESS_ADMIN_TOKEN` = `"test-admin-token-0123456789abcdef01"`; приложение через
  `create_app` + `LifespanManager` + `httpx.ASGITransport`, как `test_health.py`):
  `test_post_task_creates_plan_task` (201, `kind=plan`, `status=new`, `source=api`, `workspace_id=None`);
  `test_post_task_with_known_workspace` (id — `load_config(EXAMPLE_CONFIG).workspaces[0].id`);
  `test_post_task_unknown_workspace_422`; `test_post_task_empty_text_422`;
  `test_post_task_without_token_401_creates_nothing` (401, в БД 0 задач);
  `test_get_task_returns_events` (POST, затем `change_status` new→choosing через
  `app.state.session_factory`, GET → 200, 1 событие `choosing`); `test_get_unknown_task_404`;
  `test_get_task_without_token_401` (сценарий «Без токена»: 401 + `WWW-Authenticate: Bearer`, тело
  `{"detail": "unauthorized"}` для существующего и несуществующего id одинаково);
  `test_wrong_token_401`; `test_non_bearer_scheme_401` (`Authorization: Basic …`);
  `test_admin_token_not_configured_401` (без `HARNESS_ADMIN_TOKEN` любой bearer → 401);
  `test_invalid_id_without_token_401` (`GET /tasks/not-a-uuid` без токена → 401, не 422).
- `test_settings.py` (добавить): `test_admin_token_too_short_rejected` (31 символ → `SettingsError`, имя
  `HARNESS_ADMIN_TOKEN` в тексте, значения нет); `test_admin_token_min_length_accepted` (32 символа);
  `test_admin_token_optional` (не задан → `None`).
- `test_config.py` (добавить): `test_extended_secret_segments_rejected` (parametrize по `tokens`, `secrets`,
  `passwd`, `pwd`, `credential`, `credentials` в имени ключа, например `gitlab_pwd`); `test_gitlab_base_url_with_userinfo_rejected`
  (`https://user:pass@gitlab.example.com` → `ConfigError` с `gitlab.base_url`, без `pass` в тексте);
  `test_gitlab_base_url_with_user_only_rejected` (`https://user@gitlab.example.com`).

## Acceptance criteria

1. `./tools/harness check` зелёный (ruff check, ruff format --check, mypy strict `apps shared`, pytest), все
   перечисленные тесты существуют и проходят; `type: ignore` без комментария причины нет.
2. `openspec validate mvp-03-task-store --strict` и `openspec validate --all` без ошибок.
3. `alembic check` после `upgrade head` не находит расхождений; `downgrade base` → `upgrade head` проходит.
4. Сценарии `specs/task-lifecycle/spec.md` и `specs/platform-config/spec.md` покрыты тестами с именами выше.
5. В `api/` нет импортов `sqlalchemy`, кроме `AsyncSession` и `async_sessionmaker` из `sqlalchemy.ext.asyncio`
   в `deps.py`; в `domain/` нет `sqlalchemy`; `api/tasks.py` вызывает только `services.tasks`.
6. ARCHITECTURE.md §2 (новые пакеты), §3 (типы и ключи таблиц, `api` в `source`, `processed_at`), §9
   (`HARNESS_ADMIN_TOKEN` ≥ 32, сегменты секретов, userinfo), `.env.example`, `db/README.md`,
   `apps/server/README.md`, `shared/README.md`, `docs/glossary.md`, PLAN.md (mvp-03 → `review`) обновлены.
7. project-memory синхронизирована: `memory_status` — 0 устаревших файлов.

## Rollback

- Код: revert коммитов ветки `mvp-03-task-store` (изменение ещё не в `main`).
- БД: `uv run alembic downgrade base` (удаляет таблицы MVP; данных в проде на момент mvp-03 нет).
- Хвосты config/settings откатываются вместе с кодом; downgrade не требуется.

## Разрешённые для изменения файлы

Новые: все из таблицы «Новые файлы». Изменяемые:
`apps/server/src/harness_server/app.py`, `apps/server/src/harness_server/settings.py`,
`apps/server/src/harness_server/config.py`, `db/migrations/env.py`, `apps/server/tests/conftest.py`,
`apps/server/tests/test_settings.py`, `apps/server/tests/test_config.py`, `ARCHITECTURE.md`, `PLAN.md`,
`.env.example` (только строка и комментарий `HARNESS_ADMIN_TOKEN`; по явному разрешению оркестратора),
`db/README.md`, `apps/server/README.md`, `shared/README.md`, `docs/glossary.md`,
`openspec/changes/mvp-03-task-store/tasks.md` (отметки `[x]`).
Не трогать: `worker.py`, `cli.py`, `api/health.py`, `docker-compose.yml`, `Dockerfile`, `pyproject.toml`
(оба), `uv.lock`, `docs/decisions.md` (уже обновлён Architect), остальные OpenSpec-изменения.

## Risks / Trade-offs

- [Ветвление статусов разрастётся] → все переходы в одной таблице с тестами достижимости и выхода.
- [Задача `plan` не меняет статус, пока её выполняет worker (`planning` → … → `ready`)] → `claim_next_task`
  требует перехода; способ захвата `plan` (переход или отметка захвата) решает `mvp-06-sandbox-runtime`.
  В MVP одна песочница и один worker.
- [`alembic check` и non-native `Enum`] → не проверено исследованием; при расхождении типа — стоп и эскалация
  (п. 7), без обходов.
- [`created_at = now()` — время начала транзакции] → порядок событий `created_at, id`; `uuid7` монотонен в
  процессе.
- [Короткий `HARNESS_ADMIN_TOKEN` в существующем окружении] → сервер не стартует с понятной ошибкой; D-23.
