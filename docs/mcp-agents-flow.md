# MCP `agents-flow` — каталог инструментов

Адрес: `${HARNESS_PUBLIC_URL}/mcp` (Streamable HTTP). Авторизация: `Authorization: Bearer <token>`.
Логика каждого инструмента — функция в `services/`; инструмент только проверяет доступ и валидирует вход.
Каждый вызов пишет событие с источником (`agent`, `telegram`, `console`, `external`).

## Доступ

| Токен | Кто | Видит |
|---|---|---|
| Токен задачи, роль `planner` | Агент задачи `plan` | Свою задачу и свой workspace |
| Токен задачи, роль `implementer` | Агент задачи `implement` | Свою задачу |
| Операторский (`read`/`operate`/`admin`) | Telegram, консоль, внешний клиент | Всё по скоупу (после MVP) |

Ошибки: `unauthorized` (нет/просрочен токен), `forbidden` (чужая задача или роль), `invalid_input`,
`invalid_transition` (недопустимая смена статуса), `confirm_required` (опасный инструмент без `confirm=true`).

## MVP

| Инструмент | Роль | Вход | Эффект |
|---|---|---|---|
| `report_task` | planner, implementer | `status`: `started`\|`progress`\|`completed`\|`failed`, `text` | `TaskEvent`; `completed` у исполнителя запускает гейты; обновление сообщения в Telegram |
| `sync_spec` | planner | `change_id`, `items[]`: `key`, `text`, `status` | Upsert `SpecItem` по (`workspace`, `change_id`, `key`); возвращает список с id |
| `create_task` | planner | `text`, `spec_item_key`, `priority?` | Задача `implement` в `backlog` в своём workspace, `source=spec`, `parent_id` = задача плана |
| `list_tasks` | planner, implementer | `status?` | Задачи своего workspace (id, kind, status, text) |

## После MVP

| Группа | Инструменты | Изменение |
|---|---|---|
| Агент | `save_checkpoint`, `report_process`, `heartbeat`, `save_handoff` | `checkpoints`, `processes`, `agent-heartbeat`, `agent-sessions` |
| Skills/MCP | `skills_manifest`, `get_skill`, `get_mcp_config` | `skills-library`, `integrations-mcp-config` |
| Задачи (оператор) | `create_task`, `get_task`, `choose_workspace`, `pause_task`, `resume_task`, `stop_task`(confirm), `retry_task`, `set_task_priority`, `task_history`, `agent_status` | `mcp-operator-tools` |
| Песочницы | `list_sandboxes`, `create_sandbox`, `pause_sandbox(es)`, `resume_sandbox(es)`(confirm для всех), `delete_sandbox`(confirm) | `sandbox-pool`, `control-commands` |
| Процессы/чекпоинты | `list_processes`, `list_checkpoints`, `get_checkpoint` | `processes`, `checkpoints` |
| Спецификация | `list_spec`, `sync_spec` | `mcp-operator-tools` |
| Workspace/агенты | `list_workspaces`, `get_workspace`, `update_workspace`, `list_agents`, `update_agent` | `console-settings` |
| Skills | `list_skills`, `upsert_skill`, `attach_skill`, `delete_skill`(confirm) | `skills-library` |
| Интеграции/MCP | `list_integrations`, `upsert_integration`, `list_mcp`, `set_mcp_value`, `delete_mcp_value` | `integrations-mcp-config` |
| Профиль | `get_profile`, `update_profile`, `get_bootstrap_link` | `sandbox-profile` |
| Бюджет/сессии | `usage(period)`, `list_sessions`, `force_handoff` | `budget-usage`, `agent-sessions` |
| Откат | `revert_task` | `revert-task` |
