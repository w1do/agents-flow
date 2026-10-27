# Развёртывание

## Сервер в Dokploy

Два Compose-стека.

### 1. База

`deploy/db/docker-compose.yml` — PostgreSQL с постоянным volume.
Наружу не публикуется, только внутри `dokploy-network`.

### 2. Приложение

Корневой `docker-compose.yml`:

| Сервис | Роль |
|---|---|
| `migrate` | Alembic, выполняется до `server` |
| `server` | FastAPI + панель + MCP |
| `console` | админ-команды (создание администратора, обслуживание) |

Требования:

- `migrate` завершается успешно до старта `server`;
- все сервисы в `dokploy-network`;
- API, панель, MCP — через Dokploy/Traefik по HTTPS;
- Harness в серверный Compose не входит;
- секреты только в Dokploy Environment;
- данные PostgreSQL переживают пересборку сервера.

## Переменные окружения

```text
DATABASE_URL
JWT_SECRET
ADMIN_EMAIL
ADMIN_PASSWORD
TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET
TRANSCRIPTION_PROVIDER
TRANSCRIPTION_API_KEY
PUBLIC_BASE_URL
```

## Harness

Ставится на машине с Git-проектом.

Требования:

- Git;
- Deep Agents;
- HTTPS до сервера;
- проектные инструменты, только если нужны назначенным skills.

```bash
harness init <project_id>
harness run
```

## Обновление

1. Собрать новый образ сервера.
2. `migrate` прогоняется автоматически.
3. Панель и API перезапускаются.
4. Harness совместим по API: изменения контракта — только с обратной совместимостью
   или новой версией endpoint.

## Откат

- Образ сервера — предыдущий тег.
- Миграции — только вперёд; откат данных — из бэкапа.
- Бэкап PostgreSQL — регулярный, проверяется восстановлением.
