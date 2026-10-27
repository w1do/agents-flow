# API

Базовый путь `/api/v1`. Все изменяющие состояние запросы требуют
`Idempotency-Key: <UUID>`; повтор с тем же ключом возвращает исходный ответ.

## Авторизация

| Кто | Заголовок |
|---|---|
| Панель | `Authorization: Bearer <jwt>` |
| Harness | `Authorization: Bearer <agent_token>` |
| `harness init` | одноразовый init-код |

## Панель и проекты

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/auth/login` | вход администратора |
| GET/POST | `/projects` | список и создание |
| GET | `/projects/{id}` | карточка |
| POST | `/projects/{id}/init-tokens` | создать init-код |
| GET/POST | `/projects/{id}/tasks` | задачи проекта |
| GET | `/tasks/{id}` | карточка задачи |
| POST | `/tasks/{id}/plan/decision` | решение по плану |
| POST | `/tasks/{id}/result/decision` | решение по результату |
| GET | `/projects/{id}/agents` | агенты проекта |

Решения:

```json
// план
{"decision": "approved", "feedback": null}   // или "rejected"
```

```json
// результат
{"decision": "publish", "feedback": null}    // "rework" | "keep_ready"
```

## Skills

| Метод | Путь | Назначение |
|---|---|---|
| GET/POST | `/skill-categories` | категории |
| PATCH | `/skill-categories/{id}` | изменить категорию |
| GET/POST | `/skills` | список и создание |
| GET/PATCH | `/skills/{id}` | карточка и правка |
| POST | `/skills/{id}/archive` | отключить |
| GET | `/agents/{id}/skills` | skills агента |
| PUT | `/agents/{id}/skills` | заменить набор |

```json
{"skill_ids": ["development-skill-id", "testing-skill-id"]}
```

## Инициализация Harness

`POST /harness/init`, авторизация init-кодом.

```json
{
  "project_id": "uuid",
  "agent_name": "landing-worker",
  "repository_path_hint": "/path/to/project",
  "git_remote": "origin"
}
```

```json
{
  "agent_id": "uuid",
  "agent_token": "только один раз",
  "server_url": "https://flow.example.com",
  "poll_interval_seconds": 5,
  "lease_ttl_seconds": 60,
  "skills": [{"filename": "development--landing.md", "version": 1, "content": "..."}]
}
```

## Harness API

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/agents/{id}/heartbeat` | продлить аренду |
| GET | `/agents/{id}/skills/sync` | обновления skills |
| POST | `/agents/{id}/leases/claim` | арендовать задачу |
| GET | `/tasks/{id}/execution-state` | статус и решение пользователя |
| POST | `/tasks/{id}/plan` | передать план |
| POST | `/tasks/{id}/events` | прогресс, checkpoint, тесты |
| POST | `/tasks/{id}/result` | итог реализации |
| POST | `/tasks/{id}/publication-result` | итог push/deploy |
| POST | `/tasks/{id}/fail` | ошибка |

## Коды ошибок

| Код | Когда |
|---|---|
| 401 | нет или протух токен |
| 403 | чужая задача, чужой проект |
| 404 | объект не найден или не виден роли |
| 409 | устаревший/чужой `lease_id`, недопустимый переход |
| 422 | невалидное тело запроса |
| 429 | слишком частое арендование |

Ошибки — JSON `{"detail": "..."}`, без внутренних деталей и секретов.
