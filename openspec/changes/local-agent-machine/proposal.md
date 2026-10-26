# Proposal

> Novita и bootstrap-скрипт удаляются полностью. Агент живёт на постоянной машине владельца (стоит там заранее),
> worker исполняет команды на ней локально, а проект подключается командой `agent init {project}`.
> Решение владельца 2026-10-24 (D-NN записывается при реализации).

## Why

Песочница Novita и `deploy/sandbox/bootstrap.sh` решали задачу «поднять чистую облачную машину под агента»: создание
песочницы вручную, установка Node, `claude`, `openspec`, Docker и memory-agent, пауза по таймауту, продление жизни.
Владелец отказывается от облачной песочницы: агент устанавливается на машину один раз и остаётся там. Установка
инструментов при каждой подготовке, зависимость от Novita (ключ, домен, SDK, квоты, таймауты) и сам bootstrap становятся
лишними. Нужна одна короткая операция подключения проекта на уже готовой машине. Остальной функционал харнесса
(очередь, задачи, MCP, worktree на задачу, гейты, память проекта, vault, Telegram) остаётся без изменений.

## What Changes

- **BREAKING** Удаляется адаптер Novita: `adapters/novita/client.py`, зависимость `novita-sandbox`, ENV `NOVITA_API_KEY`
  и `NOVITA_DOMAIN`, `docs/novita.md`, спайк `tools/spikes/novita_check.py`, тесты и live-тесты Novita.
- **BREAKING** Удаляется bootstrap: `deploy/sandbox/bootstrap.sh`, команда `harness-server sandbox bootstrap`,
  `services/sandboxes.bootstrap` и константы фаз, `COPY deploy/sandbox` в `Dockerfile`, тесты скрипта. Установка Node,
  `claude`, `openspec`, Docker, memory-agent и `acl` больше не делается харнессом: инструменты ставит владелец.
- Протокол `SandboxProvider` переезжает в нейтральный `adapters/sandbox/` (`protocol`, `errors`, `fake`) и теряет
  `extend_timeout`; новая реализация `LocalSandboxProvider` исполняет команды на машине worker подпроцессами `bash -lc`
  с очищенным окружением (в процесс агента не попадают ENV worker) и пишет файлы напрямую в файловую систему.
- Новая команда `agent` (отдельная точка входа пакета `harness-server`, тонкий вход над `services/machine`):
  `agent init {project}` идемпотентно подключает workspace `{project}` на машине: проверка предпосылок (без установки),
  раскладка `~/.harness/{bin,tasks,worktrees,projects}`, клон репозитория в `~/work/{project}` с ключом из vault,
  `~/.harness/mcp.json` с плейсхолдерами, индексация памяти проекта (`memory init`), маркер готовности проекта.
- Worker перед активацией задачи проверяет маркер готовности проекта; нет маркера — задача `error` с причиной
  `project_not_initialized` и подсказкой `agent init <id>`. Fetch и worktree на `task/<id>` не меняются.
- Конфиг `harness.yaml`: `sandbox.claude_code_version`, `sandbox.openspec_version`, `sandbox.memory.repo` и
  `sandbox.memory.ref` удаляются (версии и установка memory-agent — на владельце машины); конфиг с ними отклоняется
  с подсказкой (по образцу D-60). `sandbox.provider_id` остаётся логическим именем машины (например, `local`).
- Worker запускается на той же машине, что и агент (host-процесс под systemd, пример юнита в `deploy/worker/`);
  сервис `worker` убирается из `docker-compose.yml` стека Dokploy (остаются `migrate`, `server`).
- Документация и память: ARCHITECTURE.md, PLAN.md, `docs/deployment.md`, `apps/server/README.md`, `.env.example`,
  `config/harness.example.yaml`, `docs/glossary.md`, `docs/mcp-agents-flow.md` (без изменений каталога), D-NN.
- Согласование незакрытых изменений: `mvp-06b-vps-provider`, `sandbox-timeout-extend`, `cli-version-pin` закрываются без
  реализации; в `opencode-only-client` отменяются задачи про bootstrap и каталог-источник конфигурации; в `sandbox-pool`
  убирается создание песочниц через Novita. Пометки добавляются в их `proposal.md` (архив не редактируется).

## Capabilities

### New Capabilities

- `agent-machine`: подключение проекта на машине с агентом командой `agent init {project}` (предпосылки, раскладка
  каталогов, клон с ключом из vault, `mcp.json`, память проекта, маркер готовности) и локальное исполнение команд
  worker на этой машине без доступа к секретам worker.

### Modified Capabilities

- `sandbox-runtime`: активация без возобновления и продления у провайдера; пауза и возобновление становятся
  логическими (статус строки без вызова провайдера), команда подготовки bootstrap исчезает; креды больше не
  передаются в env bootstrap; добавляется требование о маркере готовности проекта.
- `sandbox-profile`: удаляются требования об установке (Bootstrap, memory-agent, фазы, скрипт в образе, клоны
  bootstrap); требования о ключах из vault, памяти проекта и авторизации git по workspace переносятся на `agent init`.

## Impact

- Зависит от: `sandbox-profile` (6c), `git-providers` (6e), `bootstrap-in-image` (6f) — их результат частично
  заменяется; `mvp-06-sandbox-runtime` (рантайм worktree/агента сохраняется). Порядок: до `mvp-07`.
- Ссылки: ТЗ §9 (песочницы, модель), §13 (профиль песочницы), §7 (диспетчер), ограничения A5 (гонка за песочницу),
  C8 (версии CLI: теперь ответственность владельца машины); D-35…D-38, D-40, D-47, D-51, D-52, D-60, D-62, D-63.
- Код: `adapters/novita` → `adapters/sandbox` и `adapters/local`; `services/sandboxes.py` (удаляются `bootstrap`,
  `extend_timeout` в `activate`, `ensure-docker` в `_sync_memory`); новый `services/machine.py`; `cli.py`;
  новый `agent_cli.py`; `wiring.py`, `settings.py`, `config.py`, `worker/__init__.py`, `worker/dispatcher.py`.
- Зависимости: убирается `novita-sandbox` (и `uv.lock`). Новых нет.
- ENV: удаляются `NOVITA_API_KEY`, `NOVITA_DOMAIN`. Для `agent init` нужны `HARNESS_CONFIG`, `VAULT_MCP_URL`,
  `VAULT_MCP_TOKEN`, `HARNESS_PUBLIC_URL` (опционально), без `DATABASE_URL` и Telegram.
- БД: без миграций (таблица `sandboxes` и `provider_id` остаются; имена не переименовываются).
- Деплой: worker выезжает из Compose на хост; `deploy/db` публикует Postgres только на `127.0.0.1` (см. design).
- Риск: исчезает изоляция облачной VM; агент с `bypassPermissions` работает на машине владельца (design, Risks).

## Не входит

- Переход клиента на OpenCode, запуск `opencode` и разбор его вывода: остаётся в `opencode-only-client` (в
  урезанном виде, без bootstrap и каталога-источника).
- Несколько машин, пул и выбор провайдера на задачу: одна машина, `sandbox-pool` остаётся отдельным изменением.
- Подключение машины по SSH и пакет `asyncssh` (`mvp-06b-vps-provider` закрывается).
- Установка и обновление Node, `claude`/`opencode`, `openspec`, Docker, memory-agent: делает владелец вручную;
  `agent init` только проверяет их наличие.
- Docker-, namespace- или VM-изоляция агента; создание отдельного пользователя ОС (рекомендация в документации).
- Переименование `sandbox`/`sandboxes`/`SandboxProvider` в коде, БД и конфиге; миграции схемы.
- Правка архива OpenSpec, ТЗ v5 и существующих записей `docs/decisions.md` (новое решение — новой записью D-NN).
- Консольные и Telegram-команды для `agent init`: команда запускается только владельцем в терминале машины.
