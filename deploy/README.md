# deploy

Compose-стеки для Dokploy.

| Путь | Что разворачивает |
|---|---|
| `db/docker-compose.yml` | PostgreSQL с постоянным volume |
| `../docker-compose.yml` | `migrate`, `server`, `console` |

Правила:

- PostgreSQL не публикуется наружу.
- Все сервисы в сети `dokploy-network`.
- Секреты — только в Dokploy Environment.
- `migrate` завершается до старта `server`.
- Harness сюда не входит.

Подробности: [../docs/deployment.md](../docs/deployment.md).
