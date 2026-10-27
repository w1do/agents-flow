# server

Центральная панель Agents Flow. Разворачивается в Dokploy.

| Слой | Технологии |
|---|---|
| API | FastAPI, Pydantic |
| БД | PostgreSQL, SQLAlchemy, Alembic |
| Панель | React, shadcn/ui |
| Telegram | webhook, транскрибация голоса |
| MCP | Streamable HTTP, тот же service layer |

## Планируемая структура

```
server/
├── app/
│   ├── api/            маршруты REST (тонкие)
│   ├── mcp/            MCP-инструменты
│   ├── services/       бизнес-логика, общая для REST и MCP
│   ├── models/         SQLAlchemy
│   ├── schemas/        Pydantic
│   ├── integrations/   telegram, transcription, dokploy-вебхуки
│   └── core/           настройки, безопасность, зависимости
├── migrations/         Alembic
├── web/                React-панель
├── tests/
└── pyproject.toml
```

## Правила

- Маршрут не содержит логики: разбор запроса → сервис → ответ.
- Одна тема — один модуль, не больше 150 строк.
- Все изменения схемы — только через миграции Alembic.
- MCP и REST вызывают одни и те же сервисы.
- Состояние задачи меняет только сервер и только по разрешённым переходам.

Документация: [../docs/architecture.md](../docs/architecture.md),
[../docs/api.md](../docs/api.md), [../docs/data-model.md](../docs/data-model.md).
