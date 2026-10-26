# Proposal

## Why

Проекты сейчас задаются вручную: блок `workspaces` в `harness.yaml`, который монтируется на сервер
в Dokploy, и отдельно `agent init` на машине агента, который пишет в `~/.harness` и `~/work`. Это два
источника правды, и настройка проекта требует правки файлов на двух машинах. Нужен один источник:
проект заводится в консоли (или через API сервера), сервер хранит его настройки, а машина агента
получает их командой `agent init <workspace>` и создаёт у себя папку с готовым конфигом.

## What Changes

- Новый capability `project-catalog`: проект (workspace) — запись на сервере с полями из
  `platform-config` (`id`, `name`, `voice_aliases`, `repo`, `default_branch`, `test_command`, `agent`,
  `agent_max_turns`). Создание, чтение, изменение и отключение проектов через сервисы сервера, которыми
  пользуются консоль (`/api/console/*`) и бот.
- Ключ репозитория по-прежнему только ссылкой `repo.access_ref` на vault; значения ключей в БД и в
  консоли не хранятся (как в `platform-config`).
- **BREAKING** для `platform-config`: список workspaces больше не берётся из `harness.yaml`. Источник —
  записи `project-catalog`. Блок `workspaces` в `harness.yaml` и его валидация переходят в
  `project-catalog`; `harness.yaml` остаётся только для глобальных настроек сервера и песочницы.
- `agent init <workspace>` на машине агента запрашивает у сервера настройки проекта и по ним создаёт
  локальную папку проекта: harness-конфиг только для этого workspace, клон репозитория, маркер готовности
  `projects/<id>.ready`. Локальный конфиг генерируется из серверной записи, руками не редактируется.
- Команда `agent init` принимает идентификатор workspace (как в `project-catalog`), не UUID.
- `sandbox-profile` (старый bootstrap) этим change не меняется: его заменяет `local-agent-machine`,
  который уже в работе. Здесь только согласуем, что источник настроек проекта — сервер.

## Capabilities

### New Capabilities
- `project-catalog`: хранение и управление проектами (workspace) на сервере; выдача настроек проекта
  машине агента по его идентификатору.

### Modified Capabilities
- `platform-config`: список workspaces переходит с `harness.yaml` на `project-catalog` (BREAKING, см. выше).

## Impact

- Сервер: новая таблица проектов (миграция Alembic в `db/migrations`), сервисы `services/projects`,
  API `/api/console/projects` и вход для бота (тонкий, вызывает тот же сервис).
- Конфиг: `harness.yaml` без блока `workspaces`; переход на боевом сервере требует переноса существующих
  workspaces в БД (см. `docs/deployment.md`, раздел миграции).
- Машина агента: `agent init` тянет настройки проекта с сервера (нужен адрес сервера и токен оператора,
  значения — из ENV, не из файлов). Зависит от `local-agent-machine` (ещё не слит).
- Консоль (`apps/console`, `mvp-10`): создание и редактирование проекта — отдельный этап, здесь только
  API, на который консоль будет опираться.
