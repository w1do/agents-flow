# harness

Go-бинарник, который ставится в Git-проект и запускает готового Deep Agents.

## Команды

```bash
harness init <project_id>   # подключить проект
harness run                 # рабочий цикл
```

## Планируемая структура

```
harness/
├── cmd/harness/        точка входа, разбор команд
├── internal/
│   ├── config/         config.yaml, .agent-token
│   ├── api/            REST-клиент сервера
│   ├── leases/         аренда, heartbeat
│   ├── skills/         синхронизация local <-> server
│   ├── workspace/      Git worktree, ветка task/<id>
│   └── agent/          запуск Deep Agents, этапы работы
├── go.mod
└── README.md
```

## Правила

- Никаких команд проекта, Dokploy, GitHub/GitLab API и сборки конкретного стека.
- Всё предметное — в skills, которые приходят с сервера.
- Токен только в `workflow/.agent-token` (0600) и только в памяти процесса.
- Каждое действие агента идемпотентно: повторный отчёт не создаёт дубликат.
- Работа только в worktree задачи, основная ветка не трогается.

Документация: [../docs/harness.md](../docs/harness.md),
[../docs/deep-agents.md](../docs/deep-agents.md).
