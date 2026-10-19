# PLAN — agents-flow harness

Порядок работ и статус изменений OpenSpec. Обновляется тем же изменением, что и код
(принятое изменение → статус `done` и `openspec archive`). Архитектура — [ARCHITECTURE.md](ARCHITECTURE.md),
решения — [docs/decisions.md](docs/decisions.md).

Статусы: `todo` — не начато, `wip` — в работе, `review` — на ревью, `done` — принято и заархивировано, `blocked` — ждёт решения.

## Текущее состояние (2026-10-19)

- Готово: ТЗ v5 сохранено, CLAUDE.md, ARCHITECTURE.md, docs/, OpenSpec-изменения для MVP (9) и после MVP (40).
- Готово и заархивировано: `mvp-01-novita-spike` (спайк Novita и Claude Code), `mvp-02-foundation` (каркас, конфиг, health, worker, Compose, GitLab CI), `mvp-03-task-store` (схема БД, статусы, очередь, /tasks), `mvp-04-telegram-intake` (webhook, STT, кнопки проекта; live-проверка 4.3 принята владельцем). Спеки `platform-config`, `task-lifecycle`, `telegram-bot`, `speech-to-text` синхронизированы в `openspec/specs/`.
- Блокеров нет: вопрос 3 закрыт (GitLab, D-01).
- Известное ограничение: пайплайн GitLab на реальном MR не запускался (remote репозитория — GitHub). Проверить при первом MR в GitLab; см. [docs/deployment.md](docs/deployment.md).
- На ревью: `mvp-05-command-routing` (ветка `mvp-05-command-routing`). Код реализован, проверки зелёные (ruff, format,
  mypy strict, pytest 642 passed / 2 deselected live, `openspec validate --strict` и `--all`), ревью и security review
  APPROVED. Открыто: задача 5.2 (live-проверка 10 фраз; модель выбирает владелец, чекбокс закрывает владелец) и 6.1
  (project-memory). Низкие находки ревью зафиксированы как известные ограничения в `design.md` (Risks).
  Статус `done` после подтверждения 5.2 и архивации. Дальше — `mvp-06-sandbox-runtime`.

## MVP — сквозной срез (ТЗ §16.0)

Критерий приёмки: голосом «создай X» → спецификация → задачи в `backlog` → агент делает одну задачу →
MR создан → сообщение в Telegram.

| # | Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|---|
| 1 | [`mvp-01-novita-spike`](openspec/changes/archive/2026-10-18-mvp-01-novita-spike/) | Проверка Novita и Claude Code в песочнице (A1, A2) | — | — | done |
| 2 | [`mvp-02-foundation`](openspec/changes/archive/2026-10-18-mvp-02-foundation/) | Каркас монорепо, конфиг, health, Compose, CI | platform-config | — | done |
| 3 | [`mvp-03-task-store`](openspec/changes/archive/2026-10-18-mvp-03-task-store/) | Схема БД, статусы, очередь, POST/GET /tasks | task-lifecycle | mvp-02 | done |
| 4 | [`mvp-04-telegram-intake`](openspec/changes/archive/2026-10-18-mvp-04-telegram-intake/) | Webhook, голос→текст, кнопки проекта, одно сообщение | telegram-bot, speech-to-text | mvp-03 | done |
| 5 | [`mvp-05-command-routing`](openspec/changes/mvp-05-command-routing/) | Polza: классы work/status, кандидаты, запасной путь | command-routing | mvp-04 | review |
| 6 | [`mvp-06-sandbox-runtime`](openspec/changes/mvp-06-sandbox-runtime/) | Адаптер Novita, bootstrap, запуск агента, очистка, пауза | sandbox-runtime | mvp-01, mvp-03 | todo |
| 7 | [`mvp-07-agents-flow-mcp`](openspec/changes/mvp-07-agents-flow-mcp/) | MCP: токен задачи, report_task, sync_spec, create_task | agents-flow-mcp | mvp-03, mvp-06 | todo |
| 8 | [`mvp-08-spec-planning`](openspec/changes/mvp-08-spec-planning/) | Планировщик OpenSpec → задачи в backlog | spec-planning | mvp-05, mvp-06, mvp-07 | todo |
| 9 | [`mvp-09-delivery-mr`](openspec/changes/mvp-09-delivery-mr/) | Исполнитель, гейты, MR в GitLab, итог в Telegram | delivery-gates | mvp-08 | todo |

`mvp-01`…`mvp-04` выполнены, `mvp-05` на ревью. Дальше строго по номеру: `mvp-06` начинается после принятия `mvp-05`.

## После MVP — мелкие изменения по волнам

Порядок внутри волны учитывает зависимости. Волну можно начинать, когда закончены зависимости её изменений,
а не вся предыдущая волна.


### Волна 1. Telegram и маршрутизация

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`telegram-other-project`](openspec/changes/telegram-other-project/) | Кнопка «Другой проект» | telegram-bot | mvp-05 | todo |
| [`routing-uncertainty`](openspec/changes/routing-uncertainty/) | Неуверенность маршрутизации и напоминание | command-routing | mvp-05 | todo |
| [`telegram-full-stages`](openspec/changes/telegram-full-stages/) | Полные этапы и кнопки задачи | telegram-bot | mvp-09 | todo |
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
| [`sandbox-timeout-extend`](openspec/changes/sandbox-timeout-extend/) | Продление сессии и повтор связи | sandbox-runtime | mvp-06 | todo |
| [`agent-sessions`](openspec/changes/agent-sessions/) | Сессии агента, пороги контекста и handoff | agent-sessions | checkpoints, budget-usage | todo |
| [`task-limits`](openspec/changes/task-limits/) | Лимиты задачи | budget | budget-usage | todo |
| [`processes`](openspec/changes/processes/) | Процессы в песочнице | task-processes | mvp-09 | todo |

### Волна 4. Доставка

| Изменение | Что даёт | Capability | Зависит от | Статус |
|---|---|---|---|---|
| [`gates-tests-deploy`](openspec/changes/gates-tests-deploy/) | Гейты тестов и деплоя по workspace | delivery-gates | processes | todo |
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
| [`sandbox-profile`](openspec/changes/sandbox-profile/) | Версионируемый профиль песочницы | sandbox-profile | sandbox-pool | todo |
| [`cli-version-pin`](openspec/changes/cli-version-pin/) | Закрепление версий CLI агентов | sandbox-profile | sandbox-profile | todo |
| [`skills-library`](openspec/changes/skills-library/) | Библиотека skills через MCP | skills-library | sandbox-profile | todo |
| [`integrations-mcp-config`](openspec/changes/integrations-mcp-config/) | Интеграции и MCP-серверы | integrations | skills-library | todo |
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
| §12 | skills-library, integrations-mcp-config, gates-tests-deploy, codex-agent |
| §14, §16.1 A | mvp-01 (A1), mvp-07 (A2), mvp-04/08/09 (A3), mvp-04 (A4), mvp-03/06 (A5) |
| §16.1 B | mvp-09 (B1, B2), repo-queue (B3), revert-task (B4), staging-auto-merge (B5) |
| §16.1 C | harness-snap (C1), agent-heartbeat (C2), task-limits (C3), mvp-05 (C4), voice-robustness (C5), confirm-second-factor (C6), db-retention-backups (C7), cli-version-pin (C8), health-alerts (C9), dry-run (C10), idle-pause (C11), workspace-settings-snapshot (C12), spec-drift (C13) |
| §15 | mvp-02, db-retention-backups |
| §17 | см. docs/open-questions.md |

