# Коммит runner и проверяемые claims: группа 12 change `agents-flow-mvp`

Дата: 2026-10-28. Ветка `feat/agents-flow-mvp-g12`.

## Запрос

Раннер не создавал коммит публикации: git появлялся только в
publication-skills, выполняемых в изолированной копии без `.git`, а
`result_data.changed_paths` сервер не проверял. Требовалось, чтобы раннер сам
создавал коммит и отдавал серверу проверяемые факты, а сервер хранил их как
`agent_reported` claims.

## Решение

1. **Коммит делает раннер.** Publication-этап фиксирует изменения в ветке
   `task/<task_id>` до отчёта `result`; harness git-работу не выполняет.
2. **Приватный индекс.** Staging, проверка путей/типов/blob и commit идут
   через одну копию индекса (`GIT_INDEX_FILE`); реальный индекс worktree
   сохраняется побайтно.
3. **`result_data.verification`.** Раннер собирает base/head sha, commits,
   структурированный status, diff_name_only и worktree_clean и пересылает их
   строгими claims.
4. **Claims — только утверждения агента.** Сервер принимает лишь
   `source: "agent_reported"` и валидирует схему
   (`server/app/schemas/git_claims.py`); claims не влияют на статус и приёмку.
5. **Смена конфига останавливает harness.** Harness проверяет hash конфига и
   падает non-retryable `ChangedError`
   (`harness/internal/config/integrity.go`), повторов нет.
6. **Значения по умолчанию.** `LEASE_TTL_SECONDS` / `POLL_INTERVAL_SECONDS` —
   60 и 5 секунд.

## Инвариант после 8 раундов правок

Подтверждённый коммит фиксирует неизменяемые `commit_sha` и успех
(`runner/runner/commit_outcome.py`). Всё дальнейшее — синхронизация индекса,
lock, временный каталог, диагностика (`rev-parse`, `diff-tree`, `show`,
`status`, `log`, `verification`) — best-effort через `guard` с накоплением
`cleanup_failed` / `stale_index` / `index_conflict`; приватный индекс
финализируется в `finally`. Расхождение HEAD с квитанцией — реальный отказ
(`CommitIntegrityError`), а не деградация. До коммита ошибки по-прежнему дают
failure.

## Ход работы

8 раундов: Sol (код) → Terra (проверки) → Astra (ревью) → Astra-Sec
(безопасность). Классы замечаний по раундам:

- удаление чужого `index.lock`;
- реконструкция секрета при усечении имён;
- обход маскирования через `&`/`&&`, экранирование и склейку кавычек;
- утечки в лог Uvicorn: исключения, `ExceptionGroup`, `__context__`;
- неполный запрет транспортных схем git (`ext`, `ftps`, `sftp`);
- потеря успешного коммита на каждом шаге очистки;
- подмена `commit_sha` из subject квитанции.

## Проверки

Итоговые полные прогоны Terra после слияния `main` в ветку:

- runner — 685 passed;
- server — 924 passed, 1 skipped (тест PostgreSQL требует
  `TEST_DATABASE_URL`);
- `git diff --check` — чисто;
- все файлы не длиннее 150 строк.

Финальный гейт Opus — `FINAL: APPROVED`.

## Открытые риски

Не блокируют выпуск, но остаются в модели угроз.

1. **Гонка HEAD.** Между чтением `head_sha` и `log` враждебный внешний
   писатель может дать несогласованную `verification` при `success: true`
   (`runner/runner/git_facts.py`). Требование эксклюзивного worktree описано
   в `runner/SECURITY.md`.
2. **Потеря типа управляющего исключения.** При отправке резервного 500 в
   `server/app/middleware/security_headers.py` теряется тип
   `SystemExit`/`KeyboardInterrupt`; утечки секрета нет.
3. **Подавление ошибок диагностики.** После коммита часть ошибок намеренно
   не поднимается, поэтому `success: true` не доказывает исправность индекса;
   факт сбоя виден только по флагам `cleanup_failed` / `stale_index` /
   `index_conflict`.
4. **Go не собирался и не запускался.** Тулчейна нет в системе; правки
   `harness/` проверены чтением кода и статически.

## Последствия

- `docs/harness.md` и `docs/api.md` уже описывают контракт коммита,
  `verification` и claims; переписывать их не потребовалось.
- В корневом `SECURITY.md` появился раздел «Известные ограничения группы 12».
- Ограничение из записи групп 9–12 («собственного шага `git commit` нет»)
  этой группой закрыто: шаг коммита есть в раннере.
