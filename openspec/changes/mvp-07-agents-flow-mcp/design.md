# Design: mvp-07-agents-flow-mcp

## Context

SDK требует, чтобы lifespan хост-приложения запускал `session_manager.run()`; смонтированное под-приложение свой
lifespan не выполняет (документация SDK, D-09).

## Goals / Non-Goals

**Goals:** инструмент = тонкая обёртка над сервисом; права проверяются до сервиса; токен бесполезен после задачи.

**Non-Goals:** OAuth, операторские сценарии, stdio-транспорт.

## Decisions

- **Монтирование:** `mcp = MCPServer("agents-flow")`, `app.mount("/mcp", mcp.streamable_http_app(json_response=True))`,
  `session_manager.run()` в lifespan `create_app`. Альтернатива — отдельный сервис MCP: второй деплой и вторая авторизация.
- **Авторизация через ASGI-middleware** на смонтированном пути: читает bearer, кладёт `AgentContext` в contextvar;
  инструменты получают его через зависимость. Токен хранится как HMAC-SHA256(`HARNESS_SECRET_KEY`, token).
- **Права ролей — декларативно:** `@agent_tool(roles={"planner"})`. Проверка принадлежности задачи — в сервисе
  (`Forbidden`), чтобы её нельзя было забыть в новом инструменте.
- **Токен** — 32 байта `secrets.token_urlsafe`, срок = `AGENT_RUN_TIMEOUT_MIN + 30 мин`, отзывается в `cleanup`.
- **`report_task.status`** — отдельный словарь отчётов агента (`started`, `progress`, `completed`, `failed`), а не
  статусы задачи: смену статуса задачи решает сервер (агент не управляет канбаном).

## Risks / Trade-offs

- [Изменения API SDK v1→v2] → версия SDK закреплена; тест поднимает приложение и вызывает инструмент клиентом SDK.
- [Утечка токена из песочницы] → короткий срок, привязка к одной задаче и роли, отзыв при очистке.
