# Harness

Go-бинарник, один файл. Ставится в Git-проект, запускает готового Deep Agents.
Своей БД, очереди и web-сервера не имеет.

## Команды

```bash
harness init <project_id>   # подключение к проекту
harness run                 # рабочий цикл
```

Init-код передаётся интерактивно или через окружение:

```bash
AGENTS_FLOW_INIT_TOKEN=<код> harness init <project_id>
```

## Что делает init

1. Находит корень Git-репозитория.
2. Читает Git remote.
3. Отправляет `POST /harness/init`.
4. Получает `agent_token` (единственный раз) и набор skills.
5. Создаёт `workflow/`:

```
workflow/
├── config.yaml
├── .gitignore
├── .agent-token
└── skills/
    ├── development--landing.md
    ├── testing--frontend.md
    ├── git--github-push.md
    └── deploy--dokploy.md
```

`.agent-token` попадает в `workflow/.gitignore`, права `0600`.

## Конфигурация

```yaml
server_url: https://flow.example.com
project_id: "uuid"
agent_id: "uuid"
workspace_path: "/absolute/path/to/project"
git_remote: "origin"
poll_interval_seconds: 5
lease_ttl_seconds: 60
```

Токен — только в `.agent-token`, не в YAML.

## Цикл run

1. Синхронизировать skills (до получения новой задачи).
2. Heartbeat и проверка доступа.
3. Атомарно арендовать одну задачу.
4. Создать worktree и ветку `task/<task_id>`.
5. Запустить Deep Agents с задачей, путём, checkpoint и skills этапа.
6. Передавать план → ждать решения → реализация → проверки → результат.
7. Ждать решения по результату.
8. При `publish` — передать skills публикации и получить итог.
9. Сообщить итог публикации.

## Синхронизация skills

Перед каждой новой задачей:

| Изменение на сервере | Действие Harness |
|---|---|
| новый skill | скачать |
| изменённый | обновить файл |
| снятый с агента | удалить локально |
| текущая задача | не трогать |

## Чего в Harness быть не должно

- команд Git, кроме создания worktree;
- GitHub/GitLab API;
- Dokploy;
- сборки и тестов конкретного проекта;
- имён фреймворков и стеков;
- знания о том, что такое «лендинг».

Всё это — в skills.

## Ошибки

- Нет связи — повтор с backoff, задача уходит в `stalled` по TTL.
- `409` по lease — задача потеряна, взять следующую.
- Агент упал — `agent_report_failure`, задача в `error`.
- Локальные логи не содержат токенов и содержимого skills.

## Установка

```
требования: Git, Deep Agents, HTTPS до сервера
```

Бинарник собирается `go build ./...` и кладётся в `PATH`.
