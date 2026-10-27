# Примеры API

Работают сейчас: `login`, `projects`, `init-tokens`, `harness/init`. Команды ниже
используют Bash, curl, jq и запущенный сервер; не включай `set -x`, так как
переменные содержат пароли и одноразовые токены.

## Login → проект → init-код → Harness

```bash
export BASE_URL=http://127.0.0.1:8000
read -r -p 'Admin email: ' ADMIN_EMAIL
read -rs -p 'Admin password: ' ADMIN_PASSWORD; printf '\n'
export ADMIN_EMAIL ADMIN_PASSWORD

JWT=$(jq -n '{email:env.ADMIN_EMAIL,password:env.ADMIN_PASSWORD}' |
  curl --fail-with-body -sS "$BASE_URL/api/v1/auth/login" \
    -H 'Content-Type: application/json' --data-binary @- | jq -er '.access_token')
unset ADMIN_PASSWORD

PROJECT_ID=$(curl --fail-with-body -sS "$BASE_URL/api/v1/projects" \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  --data '{"name":"Demo","description":"Первый проект"}' | jq -er '.id')

INIT_CODE=$(curl --fail-with-body -sS -X POST \
  "$BASE_URL/api/v1/projects/$PROJECT_ID/init-tokens" \
  -H "Authorization: Bearer $JWT" | jq -er '.code')

HARNESS=$(jq -n --arg project_id "$PROJECT_ID" --arg init_code "$INIT_CODE" \
  '{project_id:$project_id,init_code:$init_code,agent_name:"worker",
    repository_path_hint:"/path/to/project",git_remote:"git@example.test:org/repo.git"}' |
  curl --fail-with-body -sS "$BASE_URL/api/v1/harness/init" \
    -H 'Content-Type: application/json' --data-binary @-)
printf '%s\n' "$HARNESS" | jq '{agent_id,server_url,poll_interval_seconds,lease_ttl_seconds,skills}'
AGENT_TOKEN=$(printf '%s' "$HARNESS" | jq -er '.agent_token')
unset HARNESS INIT_CODE
```

Login отвечает 200 с `access_token`, `token_type: "bearer"`, `expires_in: 43200`.
Создание проекта, init-кода и Harness отвечает 201. Init-код из ответа
`init-tokens` передаётся полем `init_code` в JSON тела `/harness/init`.
Новый агент получает `skills: []`; skills администратор назначает отдельно.

## Запланировано на этап 5

Маршруты claim, plan, decision и result ещё не реализованы (задача 1.3 требует
примеры заранее). Следующие запросы показывают контракт `docs/api.md`.
`TASK_ID` и `LEASE_ID` выдаются будущим claim response; подставь их перед запуском.

Claim:

```http
POST /api/v1/agents/{agent_id}/leases/claim
Authorization: Bearer <agent_token>
Content-Type: application/json

{}
```

Ответы ниже — выдержки; опущенные поля ответа не показаны.

```json
{"task":{"id":"<task_uuid>","lease_id":"<lease_uuid>"},"skills":[]}
```

Plan, затем решение администратора:

```http
POST /api/v1/tasks/{task_id}/plan
Authorization: Bearer <agent_token>
Content-Type: application/json

{"lease_id":"<lease_uuid>","event_id":"plan-1","plan_text":"Implement the requested change"}
```

```json
{"task_id":"<task_uuid>","status":"planning","event_id":"plan-1"}
```

```http
POST /api/v1/tasks/{task_id}/plan/decision
Authorization: Bearer <admin_jwt>
Content-Type: application/json

{"decision":"approved"}
```

```json
{"id":"<task_uuid>","status":"backlog","plan_decision":"approved"}
```

Result, затем решение о публикации:

```http
POST /api/v1/tasks/{task_id}/result
Authorization: Bearer <agent_token>
Content-Type: application/json

{"lease_id":"<lease_uuid>","event_id":"result-1","result_summary":"Change is ready","result_data":{}}
```

```json
{"task_id":"<task_uuid>","status":"ready","event_id":"result-1"}
```

```http
POST /api/v1/tasks/{task_id}/result/decision
Authorization: Bearer <admin_jwt>
Content-Type: application/json

{"decision":"publish"}
```
