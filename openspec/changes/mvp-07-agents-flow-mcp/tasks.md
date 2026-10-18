# Tasks

## 1. Сервер MCP

- [ ] 1.1 Добавить `mcp` SDK (закреплённая версия), `mcp/server.py`: создание сервера, монтирование в `create_app` на `/mcp`, `session_manager.run()` в lifespan — проверка: тест клиентом SDK `list_tools` с валидным токеном
- [ ] 1.2 `mcp/auth.py`: middleware bearer → `AgentContext` (task_id, workspace_id, role), `unauthorized` для отсутствующего/просроченного/отозванного — проверка: тест «Токен после завершения задачи»
- [ ] 1.3 Декоратор `agent_tool(roles=…)` и перевод `DomainError` в ошибки MCP — проверка: тест «Исполнитель создаёт задачу»

## 2. Инструменты и сервисы

- [ ] 2.1 `report_task` → `services.tasks.add_event` + сигнал worker для `completed`/`failed`; redaction — проверка: тесты «Агент закончил работу», «Секрет в тексте отчёта»
- [ ] 2.2 `services/spec.py` (`sync_items`) + инструмент `sync_spec` — проверка: тест «Повторная синхронизация»
- [ ] 2.3 `create_task` (planner) через `services.tasks.create_task` с ограничениями kind/status/workspace — проверка: тест «Планировщик раскладывает работу»
- [ ] 2.4 `list_tasks` с фильтром workspace — проверка: тест «Чужой workspace»

## 3. Документация и проверка доступа

- [ ] 3.1 docs/mcp-agents-flow.md сверить с фактическими сигнатурами; ARCHITECTURE.md §6; PLAN.md — проверка: ревью
- [ ] 3.2 Live-проверка: из песочницы `claude` с `mcp.json` видит инструменты `agents-flow` по публичному HTTPS — проверка: вывод `claude mcp list` в PR

## 4. Память проекта

- [ ] 4.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового файла, `memory_status` без устаревших файлов
