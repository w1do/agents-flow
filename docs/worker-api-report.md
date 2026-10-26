STATUS: DONE — реализация готова к проверке оркестратором, без commit/push.
CHANGED_PATHS: полный `git status --short` ниже, включая изменения предыдущих проходов.
TASKS_DONE: 2.1–2.3, 3.1–3.3, 4.1–4.3, 4a.1–4a.4, 5.1–5.3, 6.1–6.3; ранее выполнены 1.1–1.4. Итого 23/25.
TASKS_OPEN: 6.4 — полный harness с Postgres запускает оркестратор; 6.5 — ручная проверка владельцем, не выполнялась.
CHECKS: ruff=0, format=0, mypy strict=0, harness без Postgres=0 (432 passed), openspec=0, git diff --check=0, SQL upgrade/downgrade без БД=0.
DECISIONS: D-66; детали ниже.
OPEN: интеграционные тесты Postgres не выполнены; project-memory не инициализирован.

Реализованы тонкие HTTP-входы и сервисы очереди, отчётов, heartbeat, учёта запуска и очистки.
Worker использует HTTP-адаптер с ограниченными повторами и DTO, не импортирует БД и не требует
серверных секретов/Telegram ENV. Старые сценарии dispatcher переведены на реальный HTTP API через
ASGI и Postgres; новые контрактные сценарии клиента используют respx и записанные JSON-ответы.

DECISIONS:
- Миграции 0006–0008: UNIQUE событий, heartbeat задачи, ключ запуска и фаза очистки песочницы.
- Общий external_key для отчётов; в БД SHA256 ключей событий/запуска, чтобы не сохранять случайный секрет.
- Claim с provider_id атомарно закрепляет задачу и песочницу; конкурентная регистрация песочницы безопасна.
- D-41: при восстановлении старый токен агента жив до cleanup, новый worker получает новый токен.
- Очистка отзывает все токены до локальных команд. В её фазе авторизация — worker-токен + закрепление;
  повтор подтверждения освобождения безопасен. Ошибка сохраняет песочницу в error и current_task_id.
- Heartbeat: worker каждые 10 с, серверный срок по умолчанию 120 с; stalled не имеет автоматического выхода.
- Восстановление Telegram выполняет сервер, чтобы worker обходился без БД и Telegram ENV.
- Каталог MCP не менялся: новых MCP-инструментов в этом изменении нет.

OPEN:
- Оркестратору: выполнить полный `./tools/harness check` с настоящей Postgres. Тесты очереди, отчётов,
  heartbeat, D-41, миграций и dispatcher написаны и прошли ruff/mypy; их сценарии с БД не запускались.
- Первый ограниченный harness: exit 1, 432 passed, 4 errors на Docker-фикстурах из test_tokens.py.
  До выполнения этих четырёх сценариев дело не дошло. Итоговая выборка содержит только проверки без Postgres;
  файл тестов не ослаблялся, skips не добавлялись.
- 6.5 оставлен владельцу. PIPELINES пока пуст по текущему этапу MVP; реальные plan/implement пайплайны — mvp-08/09.
- Compose, .env.example и deploy/worker вне разрешённых путей. В docs/deployment.md приведены актуальные ENV
  и готовый Compose override для проброса WORKER_API_TOKEN оператором при выкладке. Прод не менялся.
- memory_status/memory_update вернули not_initialized. Попытка memory init --no-start --no-index
  остановилась с EROFS на /home/dev/.config/project-memory/global.env вне доступного для записи worktree.
  Индекс и аннотации не обновлены.
- Перенесённая .venv содержала shebang/.pth старого checkout: ссылки исправлены только внутри этого worktree,
  зависимости не добавлялись. Ни файлов соседних checkout, ни конфигурации вне worktree не меняли.

Итоговая проверка (явная выборка без Postgres):

```bash
UV_NO_SYNC=1 UV_CACHE_DIR=/tmp/worker-api-uv-cache PYTEST_ADDOPTS="apps/server/tests/test_worker_auth.py apps/server/tests/test_worker_client.py apps/server/tests/test_worker_remote_store.py apps/server/tests/test_worker_settings.py apps/server/tests/test_worker.py::test_worker_stops_cleanly_on_sigterm apps/server/tests/test_cli.py::test_worker_requires_worker_api_token apps/server/tests/test_cli.py::test_commands_fail_fast_on_missing_config_file apps/server/tests/test_settings.py apps/server/tests/test_statuses.py apps/server/tests/test_agent_result.py apps/server/tests/test_sandbox_fake.py apps/server/tests/test_redaction.py apps/server/tests/test_tokens.py::test_generated_tokens_are_random_and_url_safe apps/server/tests/test_tokens.py::test_generated_token_has_prefix apps/server/tests/test_tokens.py::test_hash_is_hex_hmac_and_depends_on_key" ./tools/harness check
```

Последние 5 строк, exit 0:

```text
apps/server/tests/test_sandbox_fake.py .....                             [ 93%]
apps/server/tests/test_redaction.py .........................            [ 99%]
apps/server/tests/test_tokens.py ...                                     [100%]

============================= 432 passed in 1.82s ==============================
```

`openspec validate worker-api`, exit 0:

```text
Change 'worker-api' is valid
```

Статическая генерация миграций: `alembic upgrade 0005:head --sql` и `alembic downgrade 0008:0005 --sql`,
exit 0 для обеих команд. Подключения к БД не было. `compileall` — exit 0.
`git diff --check` — exit 0, вывод пустой. Проверка с Postgres и ручной rollout не выполнялись.

CHANGED_PATHS (`git status --short`):

```text
 M ARCHITECTURE.md
 M PLAN.md
 M apps/server/README.md
 M apps/server/src/harness_server/api/deps.py
 M apps/server/src/harness_server/app.py
 M apps/server/src/harness_server/cli.py
 M apps/server/src/harness_server/db/models/sandboxes.py
 M apps/server/src/harness_server/db/models/tasks.py
 M apps/server/src/harness_server/domain/errors.py
 M apps/server/src/harness_server/domain/statuses.py
 M apps/server/src/harness_server/services/sandboxes.py
 M apps/server/src/harness_server/services/tasks.py
 M apps/server/src/harness_server/settings.py
 M apps/server/src/harness_server/worker/__init__.py
 M apps/server/src/harness_server/worker/dispatcher.py
 M apps/server/src/harness_server/worker/pipeline.py
 M apps/server/tests/conftest.py
 M apps/server/tests/test_cli.py
 M apps/server/tests/test_dispatcher.py
 M apps/server/tests/test_worker.py
 M docs/decisions.md
 M docs/deployment.md
 M shared/README.md
?? apps/server/src/harness_server/adapters/worker_api.py
?? apps/server/src/harness_server/api/worker.py
?? apps/server/src/harness_server/api/worker_cleanup.py
?? apps/server/src/harness_server/api/worker_reports.py
?? apps/server/src/harness_server/api/worker_sandbox.py
?? apps/server/src/harness_server/api/worker_support.py
?? apps/server/src/harness_server/services/agent_store.py
?? apps/server/src/harness_server/services/server_recovery.py
?? apps/server/src/harness_server/services/worker_access.py
?? apps/server/src/harness_server/services/worker_heartbeat.py
?? apps/server/src/harness_server/services/worker_queue.py
?? apps/server/src/harness_server/services/worker_recovery.py
?? apps/server/src/harness_server/services/worker_reports.py
?? apps/server/src/harness_server/services/worker_sandbox.py
?? apps/server/src/harness_server/worker/agent_store.py
?? apps/server/src/harness_server/worker/client.py
?? apps/server/src/harness_server/worker/context.py
?? apps/server/src/harness_server/worker/execution.py
?? apps/server/src/harness_server/worker/runner.py
?? apps/server/src/harness_server/worker/settings.py
?? apps/server/tests/fixtures/worker/
?? apps/server/tests/test_worker_auth.py
?? apps/server/tests/test_worker_client.py
?? apps/server/tests/test_worker_heartbeat.py
?? apps/server/tests/test_worker_migrations.py
?? apps/server/tests/test_worker_queue.py
?? apps/server/tests/test_worker_remote_store.py
?? apps/server/tests/test_worker_reports.py
?? apps/server/tests/test_worker_sandbox_api.py
?? apps/server/tests/test_worker_settings.py
?? apps/server/tests/worker_api_support.py
?? db/migrations/versions/20261026_0006_worker_event_keys.py
?? db/migrations/versions/20261026_0007_worker_heartbeat.py
?? db/migrations/versions/20261026_0008_worker_sandbox_state.py
?? docs/worker-api-report.md
?? openspec/changes/worker-api/
?? shared/src/harness_shared/worker.py
?? shared/src/harness_shared/worker_reports.py
?? shared/src/harness_shared/worker_sandbox.py
```
