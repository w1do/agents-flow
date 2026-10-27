# Agents Flow — рабочее пространство

Один репозиторий, два deployable-компонента и документация.

## Карта

| Путь | Что там |
|---|---|
| `server/` | Центральная панель: FastAPI API, PostgreSQL, Telegram, транскрибация, MCP |
| `harness/` | Go-бинарник `harness`, устанавливается в Git-проект |
| `docs/` | Проектная документация, один файл на тему |
| `deploy/` | Compose-стеки для Dokploy |
| `PLAN.md` | Исходное ТЗ, источник правды по требованиям |
| `GOAL.md` | Зачем система и как выглядит успех |
| `MVP.md` | Границы первой версии |

## Как читать документы

1. [GOAL.md](GOAL.md) — цель и критерии успеха.
2. [MVP.md](MVP.md) — что входит в первую версию.
3. [docs/architecture.md](docs/architecture.md) — компоненты и их связи.
4. Остальное — по теме: `docs/api.md`, `docs/data-model.md`,
   `docs/skills.md`, `docs/harness.md`, `docs/task-lifecycle.md`,
   `docs/security.md`, `docs/deployment.md`, `docs/criteria.md`.

## Правила разработки

- Файл кода — не больше 150 строк, одна ответственность.
- Никакой жёсткой привязки Harness к Git-хостингу, Dokploy, фреймворку или
  командам проекта. Всё это — только в skills.
- Секреты не коммитятся и не логируются. В БД — только хеши.
- Изменения схемы БД — только через Alembic.
- Публикация (push/deploy) — только после решения пользователя `publish`.

## Запуск

```bash
# сервер
cd server && docker compose up

# harness
cd harness && go build ./... && ./bin/harness init <project_id>
```

## Работа с агентом в репозитории

- Задачи формулируются через skills в панели.
- Логика конкретной работы не живёт в коде harness — только в skills.
- Новый тип задачи = новая категория и skill, а не новая ветка в коде.

Раздел про сервис предпочтений: правила и контекст для любой задачи берутся
через MCP `preferences` (`get_context_for_task`, `get_folder`), а не из
выгруженных файлов.
