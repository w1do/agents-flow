# Словарь

Имена в коде, спецификациях и сообщениях берутся отсюда.

| Термин | Код | Значение |
|---|---|---|
| Харнесс | `harness` | Вся система: сервер, worker, MCP, консоль |
| Workspace | `workspace` | Проект: репозиторий, агент, команда тестов, голосовые названия |
| Проект | `workspace` | Тот же объект, что workspace, в тексте для владельца и в команде `agent init <project>`. TODO: подтвердить по тестам `test_agent_cli.py`, что `<project>` — это `workspaces[].id` |
| Задача | `Task` | Единица работы, kind: `plan`, `implement`, `check` |
| Планировщик | `planner` | Агент задачи `plan`: пишет OpenSpec и создаёт задачи `implement` |
| Исполнитель | `implementer` | Агент задачи `implement`: пишет код по пункту спецификации |
| Класс команды | `CommandClass` | `work`, `check`, `status`, `control`, `unknown` |
| Маршрутизация | `Routing` | Ответ Polza: класс, кандидаты workspace, уверенность |
| Песочница | `Sandbox` | Среда исполнения агента: локальная машина агента (`LocalSandboxProvider`, D-64), одна задача за раз |
| Машина агента | `LocalSandboxProvider` | Локальная машина, где worker запускает агента под непривилегированным пользователем (D-64). Подготовка — команда `agent init <project>` |
| Маркер проекта | `projects/<id>.ready` | Признак, что проект подготовлен `agent init`. Путь `~/.harness/projects/<id>.ready` — TODO, по раскладке задачи 4.2 и проверке задачи 5.4 (задача 4.5 не принята). Без маркера задача не запускается, причина `project_not_initialized` |
| Команда агента | `agent` | Вход `agent_cli.py` на машине агента: `agent init <project>`, коды выхода 0, 1, 2, 3 (D-64) |
| Активация | `activate` | Возобновление песочницы + выдача кредов + подготовка worktree |
| Очистка | `cleanup` | Удаление worktree, локальной ветки, кредов; разрешает паузу |
| Гейт | `Gate` | Механическая проверка сервером: секреты, коммит, тесты, push, MR |
| MR | `MR` | Внутренний термин харнесса для запроса слияния: merge request в GitLab, pull request в GitHub (D-56, D-60). Слово для владельца выбирается по провайдеру (`change_request_label`: «MR» или «PR») |
| Провайдер репозитория | `GitProviderName` | `github` или `gitlab`: задаётся у каждого workspace в `repo.provider` (D-60) |
| Пункт спецификации | `SpecItem` | Зеркало пункта OpenSpec из `tasks.md` |
| Событие задачи | `TaskEvent` | Запись в ленте этапов, источник сообщения в Telegram |
| Источник события | `TaskEventSource` | Кто записал событие: `telegram`, `agent`, `worker`, `api` |
| Роль агента | `AgentRole` | Роль токена задачи: `planner`, `implementer` |
| Токен задачи | `TaskToken` | Bearer для MCP, действует до конца задачи |
| Операторский токен | `OperatorToken` | Bearer со скоупами `read`/`operate`/`admin` (после MVP) |
| Сообщение задачи | `TaskMessage` | Одно сообщение в Telegram (карточка задачи), этапы дописываются |
| Апдейт | `TelegramUpdate` | Входящее событие Telegram, записанное до обработки; нормализованное тело — в `payload` (`IncomingText`, `IncomingVoice`, `ButtonPress`) |
| Восстановление апдейтов | `recover_pending` | При старте worker: обработка необработанных апдейтов старше 1 мин и досылка карточек; апдейты старше 24 ч списываются |
| Чекпоинт | `Checkpoint` | summary, файлы, diff (замазанный), следующий шаг |
| Handoff | `Handoff` | Передача работы между сессиями агента (после MVP) |
| Снимок | `Snapshot` | WIP-коммит `harness-snap` раз в минуту (после MVP) |
