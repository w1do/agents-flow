# PLAN — agents-flow harness

Порядок работ и статус изменений OpenSpec. Обновляется тем же изменением, что и код
(принятое изменение → статус `done` и `openspec archive`). Архитектура — [ARCHITECTURE.md](ARCHITECTURE.md),
решения — [docs/decisions.md](docs/decisions.md).

Статусы: `todo` — не начато, `wip` — в работе, `review` — на ревью, `done` — принято и заархивировано, `blocked` — ждёт решения.

## Текущее состояние (2026-10-26)

- `mvp-08-spec-planning` — `blocked` на проверках Postgres: код гейтов, MCP планировщика,
  worker API состояния/завершения, зарегистрированного plan и Telegram-итога реализован (D-67).
  Проверены пайплайн с фейками, официальный MCP-транспорт и настоящий Git/OpenSpec на локальном origin.
  Postgres-набор не дошёл до сценариев из-за запрета Docker; атомарность и серверная изоляция
  требуют прогона в среде оркестратора. Пункты с неподтверждёнными сценариями не отмечены.
  Исправлено удержание блокировки плана при повторном finish перед Telegram-уведомлением;
  регрессия проверяет параллельные и последовательные повторы для одной и трёх дочерних задач.
  Прогон регрессии с Postgres пока заблокирован доступом к Docker; TEST_DATABASE_URL не задан.
  3.3 — за владельцем, 4.1 и полный harness check — за оркестратором.
  Исправлена остановка worker после регистрации plan: SIGTERM/SIGINT отменяют текущий dispatch,
  включая ожидание recover/claim, до закрытия HTTP. Два исходных SIGTERM-теста и три регрессии
  остановки прошли; полный прогон test_worker.py/test_worker_plan_api.py: 5 passed, 5 ошибок
  подготовки Postgres из-за запрета Docker. Ruff check/format и mypy strict затронутых файлов прошли.
  `timeout 120 ./tools/harness check`: общие ruff/format/mypy прошли, pytest остановлен
  таймаутом (exit 124) на test_local_provider.py после ошибок подготовки БД.

- `worker-api` — `review`: реализованы 1–5, включая добавленную группу 4a (D-41),
  и документация 6.1–6.3. Worker использует HTTP API без БД; восстановление Telegram работает
  на сервере в фоне без ожидания БД при старте. Тест recovery ждёт завершения фонового прохода
  в lifespan и проверяет повторный старт без дублей задач и сообщений. В Compose переданы worker ENV, ожидания
  deployment-теста учитывают postgres и console. Новые миграции 0006–0008. Полный `harness check` с Postgres (6.4) запускает
  оркестратор; ручная проверка 6.5 — за владельцем. Изменение не принято и не архивировано.
  Локальный прогон `test_worker.py`: SIGTERM пройден; recovery заблокирован доступом к Docker.
  Регрессия CLI ENV (5.4): `worker` проверяется с минимальным `WorkerSettings`, без серверных
  секретов, БД и Telegram; `serve` и `check-config` проверяют полный серверный ENV.
  Регрессия `migrate` исправлена: требуется только `DATABASE_URL`, как в Compose; существующий
  тест миграции пустой БД сохранён без изменений. Проверки выполняются через `uv run --no-sync`.
  Локально: CLI ENV — 36 passed; `test_migrate.py` и `test_cli.py` — 24 passed, 5 ошибок подготовки
  БД из-за запрета доступа к Docker. Ruff check/format и mypy strict по затронутому коду прошли.

- Готово: ТЗ v5 сохранено, CLAUDE.md, ARCHITECTURE.md, docs/, OpenSpec-изменения для MVP (9) и после MVP (40).
- Готово и заархивировано: `git-providers` (6e, D-60, D-62), `bootstrap-in-image` (6f, D-63), `mvp-01-novita-spike`, `mvp-02-foundation`, `mvp-03-task-store`, `mvp-04-telegram-intake`,
  `mvp-05-command-routing` (модель `anthropic/claude-haiku-5.5`, live 10/10, D-55; голос через бота проверен на проде
  2026-10-19), `mvp-06-sandbox-runtime` (live Novita 6/6, рантайм агента 2/2, демо «Контакты в README»; ложный «успех» при
  исчерпанном лимите Claude исправлен, D-54), `sandbox-profile` (6c: ключи из vault, Node 22, Docker, memory-agent по sha,
  авторизация git заголовком; live 7/7, D-50…D-53). Спеки `platform-config`, `task-lifecycle`, `telegram-bot`,
  `speech-to-text`, `command-routing`, `sandbox-runtime`, `sandbox-profile` синхронизированы в `openspec/specs/`.
- Прод (2026-10-20): `https://flow.w1do.ru` в Dokploy (D-59), секреты в vault `agents-flow/harness/*`; Telegram в обе стороны
  через Cloudflare Worker владельца (D-61: `TELEGRAM_API_URL`, `TELEGRAM_WEBHOOK_URL`). Бот принимает текст и голос,
  ставит задачи и отвечает о статусе; worker задачи пока не выполняет — `PIPELINES` пуст до `mvp-08`/`mvp-09`.
  Workspace `chistotyumen` переведён на GitHub (`repo.provider: github`, `w1do/chistotyumen`), ключ берётся из vault (D-60);
  bootstrap песочницы выполнен владельцем из терминала worker 2026-10-20, exit 0.
- Блокеров нет: вопрос 3 закрыт (GitLab, D-01); репозитории workspace — GitHub или GitLab по выбору workspace (D-60).
- `project-setup-via-flow` (D-65) — реализован в своей ветке: каталог проектов в БД, API `/api/console/projects`, настройки для `agent init` с сервера, `harness.yaml` без `workspaces`. Открыты: 1.1 (слияние `local-agent-machine`) и 7.3 (ручная проверка владельцем); перенос боевых проектов — по [docs/deployment.md](docs/deployment.md), раздел D-65.
- `local-agent-machine` — в работе, не принято целиком. Astra приняла только deployment artifacts task 6 (Compose worker removed, host systemd user unit, DB loopback publication); локальные artifact checks прошли. Unit/database/live runtime не развёртывались. Runtime task 3–5 остаётся заблокирован прежним finding: отсутствует успешный повторный тест 4.5; ранее отклонённые пункты не считаются принятыми. Живая приёмка владельцем (8.2) не заявлена.
- `local-agent-machine`: task 7.1 proposal updates приняты нормативным ревью; documentation tasks 7.2–7.3 подготовлены. Это не означает полной приёмки изменения: пункты 3–5 отклонены/заблокированы до успешного повторного теста 4.5, а 8.2 требует живой приёмки владельцем.
- Закрыты без реализации как superseded: `mvp-06b-vps-provider`, `sandbox-timeout-extend`, `cli-version-pin`. `opencode-only-client` остаётся частичным, клиентская часть сохранена; `sandbox-pool` и `integrations-mcp-config` остаются будущими возможностями.
- Известное ограничение: пайплайн GitLab на реальном MR не запускался (remote репозитория — GitHub). Проверить при первом MR в GitLab; см. [docs/deployment.md](docs/deployment.md).
- Следующее: `mvp-07-agents-flow-mcp`, затем `mvp-08`, `mvp-09` (D-53). Критерий владельца для 7 и 9 — D-56: агент коммитит и
  вызывает «сдать работу», push и MR делает харнесс после гейтов.
- Решено 2026-10-19: доработка задачи и диалог с агентом через Telegram — отдельное изменение `task-rework` после `mvp-09`
  (приоритет владельца).
- Решение 2026-10-19 (D-39): веб-панель оператора входит в MVP как `mvp-10-operator-console` после `mvp-09`.
- Решение 2026-10-19 (D-43, порядок изменён D-53): `sandbox-profile` (6c) и `integrations-mcp-config` (6d) делаются сразу после `mvp-06`,
  до `mvp-07`. Репозитория профиля нет; раздел MCP — таблица на платформе (D-46). Открытые вопросы владельцу — в начале их
  `proposal.md`.

## MVP — сквозной срез (ТЗ §16.0)

Критерий приёмки: голосом «создай X» → спецификация → задачи в `backlog` → агент делает одну задачу →
MR создан → сообщение в Telegram. Тот же поток виден и проверяется в веб-панели (`mvp-10`, D-39).

| # | Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|---|
| 1 | [`mvp-01-novita-spike`](openspec/changes/archive/2026-10-18-mvp-01-novita-spike/) | Проверка Novita и Claude Code в песочнице (A1, A2) | — | — | done |
| 2 | [`mvp-02-foundation`](openspec/changes/archive/2026-10-18-mvp-02-foundation/) | Каркас монорепо, конфиг, health, Compose, CI | platform-config | — | done |
| 3 | [`mvp-03-task-store`](openspec/changes/archive/2026-10-18-mvp-03-task-store/) | Схема БД, статусы, очередь, POST/GET /tasks | task-lifecycle | mvp-02 | done |
| 4 | [`mvp-04-telegram-intake`](openspec/changes/archive/2026-10-18-mvp-04-telegram-intake/) | Webhook, голос→текст, кнопки проекта, одно сообщение | telegram-bot, speech-to-text | mvp-03 | done |
| 5 | [`mvp-05-command-routing`](openspec/changes/archive/2026-10-19-mvp-05-command-routing/) | Polza: классы work/status, кандидаты, запасной путь | command-routing | mvp-04 | done |
| 6 | [`mvp-06-sandbox-runtime`](openspec/changes/archive/2026-10-19-mvp-06-sandbox-runtime/) | Адаптер Novita, bootstrap, запуск агента, очистка, пауза | sandbox-runtime | mvp-01, mvp-03 | done |
| 6c | [`sandbox-profile`](openspec/changes/archive/2026-10-19-sandbox-profile/) | Bootstrap без участия владельца: Node 22, Docker, memory-agent, ключи из vault, память проекта (D-43…D-45, D-47, D-48). Live 7/7, принято владельцем 2026-10-19 | sandbox-profile, sandbox-runtime | mvp-06 | done |
| 6d | [`integrations-mcp-config`](openspec/changes/integrations-mcp-config/) | Раздел MCP на платформе, генерация `mcp.json` агента на каждый запуск, CLI `harness-server mcp` (D-46). Отложено после `mvp-09` (D-53) | integrations, sandbox-runtime | sandbox-profile | todo |
| 6e | [`git-providers`](openspec/changes/archive/2026-10-20-git-providers/) | Репозиторий workspace на GitHub или GitLab: `workspaces[].repo`, ключ из vault по workspace, git-заголовок на префикс репозитория (D-60). Ревью и security-ревью APPROVED (D-62: перекрытия конфига git, bootstrap в три шага; `GIT_AUTH_HEADER_<i>` удалён). Live: прод bootstrap 2026-10-20, exit 0 (`w1do/chistotyumen`, главный ключ GitHub) | platform-config, sandbox-profile, sandbox-runtime | sandbox-profile | done |
| 6f | [`bootstrap-in-image`](openspec/changes/archive/2026-10-20-bootstrap-in-image/) | Скрипт bootstrap в образе, путь по умолчанию от корня приложения, не от cwd (D-63): bootstrap из терминала Dokploy | sandbox-profile | sandbox-profile | done |
| 7 | [`mvp-07-agents-flow-mcp`](openspec/changes/mvp-07-agents-flow-mcp/) | MCP: токен задачи, report_task, sync_spec, create_task | agents-flow-mcp | mvp-03, mvp-06 | todo |
| 8 | [`mvp-08-spec-planning`](openspec/changes/mvp-08-spec-planning/) | Планировщик OpenSpec → задачи в backlog | spec-planning | mvp-05, mvp-06, mvp-07 | blocked |
| 9 | [`mvp-09-delivery-mr`](openspec/changes/mvp-09-delivery-mr/) | Исполнитель, базовые гейты безопасности и гейты проекта (D-58), MR в GitLab или PR в GitHub (`adapters/git`, D-60), итог в Telegram | delivery-gates | mvp-08, git-providers | todo |
| 10 | [`mvp-10-operator-console`](openspec/changes/mvp-10-operator-console/) | Веб-панель: вход, канбан, карточка и создание задачи, песочница и логи агента | operator-console | mvp-06, mvp-09 | todo |

`mvp-01`…`mvp-06`, 6c, 6e и 6f выполнены. Дальше строго
по номеру до `mvp-10`. `sandbox-profile` (6c) — между `mvp-06` и `mvp-07` (D-43), done после подтверждения владельца; `git-providers` (6e, D-60) — до `mvp-07` по решению владельца 2026-10-19: worker должен скоро работать с GitHub-репозиторием; `mvp-09` зависит от него (`adapters/git`). `integrations-mcp-config` (6d) отложен после `mvp-09` (D-53): порядок `mvp-07` → `mvp-08` → `mvp-09` ведёт к первому MR end-to-end как можно раньше. В MVP-критерий 6c, 6d и 6e не входят.

## После MVP — мелкие изменения по волнам

Порядок внутри волны учитывает зависимости. Волну можно начинать, когда закончены зависимости её изменений,
а не вся предыдущая волна.


### Волна 1. Telegram и маршрутизация

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`telegram-other-project`](openspec/changes/telegram-other-project/) | Кнопка «Другой проект» | telegram-bot | mvp-05 | todo |
| [`routing-uncertainty`](openspec/changes/routing-uncertainty/) | Неуверенность маршрутизации и напоминание | command-routing | mvp-05 | todo |
| [`telegram-full-stages`](openspec/changes/telegram-full-stages/) | Полные этапы и кнопки задачи | telegram-bot | mvp-09 | todo |
| [`task-rework`](openspec/changes/task-rework/) | Доработка по замечанию владельца (та же ветка и MR) и диалог с агентом через Telegram (D-57). Приоритет владельца: **важно** | task-dialog, command-routing, telegram-bot | mvp-09, mvp-07 | todo |
| [`voice-robustness`](openspec/changes/voice-robustness/) | Надёжность голосового пути | speech-to-text | mvp-04 | todo |
| [`check-tasks`](openspec/changes/check-tasks/) | Задачи проверки (класс «проверка») | task-lifecycle | mvp-09 | todo |

### Волна 2. MCP оператора

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`operator-tokens`](openspec/changes/operator-tokens/) | Операторские токены и журнал вызовов | agents-flow-mcp | mvp-07 | todo |
| [`mcp-operator-tools`](openspec/changes/mcp-operator-tools/) | Операторские инструменты задач и спецификации | agents-flow-mcp | operator-tokens | todo |

### Волна 3. Надёжность исполнения и управление

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`budget-usage`](openspec/changes/budget-usage/) | Учёт расхода токенов | budget | mvp-09 | todo |
| [`status-commands`](openspec/changes/status-commands/) | Команды статуса | command-routing | mvp-05, budget-usage | todo |
| [`checkpoints`](openspec/changes/checkpoints/) | Чекпоинты агента | agent-checkpoints | mvp-09 | todo |
| [`task-pause-resume`](openspec/changes/task-pause-resume/) | Пауза и возобновление задачи | task-lifecycle | checkpoints | todo |
| [`control-commands`](openspec/changes/control-commands/) | Голосовые команды управления | command-routing | mcp-operator-tools, task-pause-resume | todo |
| [`confirm-second-factor`](openspec/changes/confirm-second-factor/) | Второй фактор для опасных команд | telegram-bot | control-commands | todo |
| [`harness-snap`](openspec/changes/harness-snap/) | Снимки работы раз в минуту | agent-checkpoints | checkpoints | todo |
| [`agent-heartbeat`](openspec/changes/agent-heartbeat/) | Heartbeat агента и статус stalled | sandbox-runtime | mvp-07 | todo |
| [`sandbox-timeout-extend`](openspec/changes/sandbox-timeout-extend/) | Superseded `local-agent-machine`, закрыто без реализации | sandbox-runtime | mvp-06 | closed |
| [`agent-sessions`](openspec/changes/agent-sessions/) | Сессии агента, пороги контекста и handoff | agent-sessions | checkpoints, budget-usage | todo |
| [`task-limits`](openspec/changes/task-limits/) | Лимиты задачи | budget | budget-usage | todo |
| [`processes`](openspec/changes/processes/) | Процессы в песочнице | task-processes | mvp-09 | todo |

### Волна 4. Доставка

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`gates-tests-deploy`](openspec/changes/gates-tests-deploy/) | Пресеты гейтов (content, data, docs), гейты задачи (только добавляют), файл гейтов из основной ветки, деплой (D-58) | delivery-gates | processes, mvp-09 | todo |
| [`staging-auto-merge`](openspec/changes/staging-auto-merge/) | Авто-мердж через staging | delivery-gates | gates-tests-deploy | todo |
| [`revert-task`](openspec/changes/revert-task/) | Откат влитой задачи | delivery-gates | staging-auto-merge | todo |
| [`spec-approval`](openspec/changes/spec-approval/) | Утверждение спецификации кнопкой | spec-planning | mvp-08 | todo |
| [`spec-drift`](openspec/changes/spec-drift/) | Расхождение спецификации и зеркала | spec-planning | mvp-08 | todo |
| [`dry-run`](openspec/changes/dry-run/) | Тестовый прогон workspace | delivery-gates | gates-tests-deploy | todo |

### Волна 5. Пул, профиль, skills

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`sandbox-pool`](openspec/changes/sandbox-pool/) | Пул песочниц | sandbox-runtime | mvp-06, operator-tokens | todo |
| [`stalled-reassign`](openspec/changes/stalled-reassign/) | Перенос сорванной задачи | sandbox-runtime | agent-heartbeat, sandbox-pool, harness-snap | todo |
| [`repo-queue`](openspec/changes/repo-queue/) | Очередь на репозиторий | delivery-gates | sandbox-pool | todo |
| [`idle-pause`](openspec/changes/idle-pause/) | Пауза простаивающих песочниц | sandbox-runtime | sandbox-pool | todo |
| `keyed-git-outside-sandbox` | Git с ключом вне песочницы или песочница на workspace — закрытие R-1 (D-62) | sandbox-profile | git-providers | todo |
| [`cli-version-pin`](openspec/changes/cli-version-pin/) | Superseded `local-agent-machine`, закрыто без реализации | sandbox-profile | sandbox-profile | closed |
| [`skills-library`](openspec/changes/skills-library/) | Библиотека skills и агентов Claude через MCP (D-49) | skills-library | sandbox-profile, mvp-07 | todo |
| [`codex-agent`](openspec/changes/codex-agent/) | Второй тип агента: Codex | sandbox-runtime | sandbox-pool, skills-library | todo |

### Волна 6. Консоль

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`console-auth`](openspec/changes/console-auth/) | Консоль: каркас и вход администратора | operator-console | operator-tokens | todo |
| [`console-settings`](openspec/changes/console-settings/) | Консоль: настройки агентов, workspace и песочниц | operator-console | console-auth, sandbox-profile, skills-library, integrations-mcp-config | todo |
| [`workspace-settings-snapshot`](openspec/changes/workspace-settings-snapshot/) | Фиксация настроек workspace на старте задачи | task-lifecycle | console-settings | todo |
| [`console-observability`](openspec/changes/console-observability/) | Консоль: канбан и наблюдаемость | operator-console | console-auth, mcp-operator-tools | todo |

### Волна 7. Эксплуатация

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`db-retention-backups`](openspec/changes/db-retention-backups/) | Хранение данных и бэкапы | operations | mvp-09 | todo |
| [`health-alerts`](openspec/changes/health-alerts/) | Внешний healthcheck и «жив» | operations | mvp-04 | todo |

## Покрытие ТЗ

| Раздел ТЗ | Изменения |
|---|---|
| §5, §5.0 | mvp-04, mvp-05, mvp-08, telegram-other-project, routing-uncertainty, check-tasks |
| §5.1 | control-commands, task-pause-resume, confirm-second-factor |
| §6 | mvp-04, mvp-08, mvp-09, telegram-full-stages, status-commands |
| §7 | mvp-02, mvp-03, mvp-06, sandbox-timeout-extend, stalled-reassign |
| §8 | console-auth, console-observability, console-settings |
| §9, §13 | mvp-01, mvp-06, sandbox-pool, sandbox-profile, idle-pause, cli-version-pin |
| §10, §10.1 | mvp-06, mvp-08, mvp-09, checkpoints, harness-snap, agent-sessions, budget-usage, task-limits, processes |
| §11 | mvp-07, operator-tokens, mcp-operator-tools (+ инструменты в профильных изменениях) |
| §12 | skills-library, integrations-mcp-config (раздел MCP), gates-tests-deploy, codex-agent |
| §14, §16.1 A | mvp-01 (A1), mvp-07 (A2), mvp-04/08/09 (A3), mvp-04 (A4), mvp-03/06 (A5) |
| §16.1 B | mvp-09 (B1, B2), repo-queue (B3), revert-task (B4), staging-auto-merge (B5) |
| §16.1 C | harness-snap (C1), agent-heartbeat (C2), task-limits (C3), mvp-05 (C4), voice-robustness (C5), confirm-second-factor (C6), db-retention-backups (C7), cli-version-pin (C8), health-alerts (C9), dry-run (C10), idle-pause (C11), workspace-settings-snapshot (C12), spec-drift (C13) |
| §15 | mvp-02, db-retention-backups |
| §17 | см. docs/open-questions.md |
