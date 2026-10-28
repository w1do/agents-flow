STATUS: DONE

# Sol (13): раунд 4 — Astra 11 / Astra-Sec 12

Проект: `/home/dev/agents-server-g12`, ветка `feat/agents-flow-mvp-g12`.
Изменения прошлых раундов сохранены. Коммит проекта не создавался; тестовые Git
операции выполнялись только в fixture-репозиториях `/tmp`.

1. **P1: реальный индекс и HEAD.** `private_index.py` сохраняет исходные байты,
   готовит и проверяет копию на том же filesystem, выполняет commit по ней.
   Затем получает реальный `index.lock` через O_EXCL, повторно сверяет исходный
   индекс и атомарными rename устанавливает проверенную копию. При чужом lock,
   изменении индекса или отказе синхронизации чужой индекс сохраняется;
   verification содержит `index_conflict=true`, `stale_index=true`, без провала
   публикации. Worktree_clean вычисляется по реальному индексу, HEAD и worktree.
   Регрессии: успешный commit и обычный пустой git status/diff --cached; гонки
   staging/lock; успешный finish_checks с конфликтом; изменение индекса после commit.
   Два прежних теста сохранения старого индекса обновлены под исправленный контракт.
2. **HIGH: config.worktree/includes.** Перед каждой операцией runner и harness
   выполняют config --list --show-origin --includes --null по всем областям;
   extensions.worktreeConfig дополнительно включает явное перечисление --worktree.
   Clean/smudge/process/required и diff command/textconv нейтрализуются заново;
   фиксированные защитные -c имеют приоритет. Include.path участвует только в
   обнаружении, не превращается в защитное переопределение. Тесты подключают
   worktree/local includes и global/system filter после создания GitFacts;
   required process не запускается. Go: поздние worktree/local/global filters,
   разбор origins/system config и запрет include.path в safety overrides.
3. **HIGH: lazy fetch/transport.** Все Git-процессы получают GIT_NO_LAZY_FETCH=1,
   core.sshCommand=/bin/false, protocol.file.allow=never и protocol.allow=never.
   Harness Clone(..., allowLocal=true) — отдельное явное разрешение local remote
   только для clone --no-checkout. История не получает разрешение.
   Python/Go-регрессии удаляют promisor blob и проверяют отсутствие запуска SSH;
   Go дополнительно проверяет env/options и opt-in локального clone.
4. **HIGH: bind-mount того же st_dev.** Новый mounts.py читает /proc/self/mountinfo,
   декодирует octal escapes и отклоняет пути под известными вложенными mounts.
   Проверки включены в Workspace, listing, safe_fs pinned fd и commit_paths.
   Семь регрессий с одинаковым st_dev проверяют directory/read/write/list/is_file/
   artifact/commit, включая пробел в mount-point; запись при отказе не выполняется.
   SECURITY.md и deploy/README.md запрещают mounts внутри worktree и требуют
   доступного mountinfo и отсутствия прав менять mounts. Конкурентные изменения
   mounts привилегированным процессом вне модели. Реальный bind-mount не создавался.
5. **MEDIUM: root_path.** BodyLimitMiddleware удаляет префикс только по границе `/`.
   Два ASGI-теста с root_path=/prefix покрывают prefixed и уже относительный path;
   превышение тела отклоняется с 422 до приложения.
6. **MEDIUM: полное маскирование токена и event_id.** Политика выделяет компоненты
   до query/fragment, но удаляет весь токен вместе с хвостом, включая `=` и скобки
   внутри query, до пробела/кавычки/`,`/`;`. Пути маскируются до credential patterns,
   чтобы промежуточный [REDACTED] не оставлял хвост. Event_id с защищённым путём
   отклоняется с 422; допустимые ID сохраняют идемпотентность.
   Регрессии runner/server: key.PEM?marker=42, src/private.key, .secrets/x,
   .NPMRC, разделители и query с [REDACTED]; HTTP-тесты трёх защищённых event_id.
7. **MEDIUM: скрытые untracked.** Во всех рабочих командах установлены
   core.excludesFile=/dev/null и status.showUntrackedFiles=all; runner status
   также явно задаёт --untracked-files=all. Python/Go-тесты используют внешний
   excludesFile и status.showUntrackedFiles=no; новый файл остаётся видимым,
   а verification не сообщает чистый worktree.
8. **MEDIUM: исключения в логах.** SecurityHeadersMiddleware пишет только
   серверно очищенный текст через logger.error без exc_info/сырого traceback.
   Регрессия проверяет 500, отсутствие credential/path/query-маркера в caplog
   и наличие [REDACTED]. Тест явно включает свой logger: SDK lifespan предыдущих
   тестов может отключить существующие loggers process-wide; проверки не ослаблены.
9. **P2: глубина.** Bounded_payload итеративно ограничивает вложенность до 32,
   до json.dumps и рекурсивной очистки. Checkpoint проверяется той же политикой.
   Body middleware дополнительно ограничивает структурную глубину до JSON decoder,
   учитывая строки и escapes. Четыре HTTP-теста payload глубины 40 дают 422;
   глубина 32 принимается, checkpoint и прямой Pydantic-вызов глубины 33 отклоняются.
   Отдельный тест отклоняет 2000 уровней до decoder; скобки внутри строк допустимы.
10. **P2: легитимный текст.** Текстовая политика сохраняет dotted `.key`
    идентификаторы без явного контекста пути; explicit safe_path/claim paths
    продолжают строгую проверку компонентов. Runner/server сохраняют все примеры:
    Fix KeyboardEvent.key handling; {"event.key":"Enter"}; const key = event.key;.
    Дополнительно проверены настоящий dict и safe_command. Защищённые .secrets/x,
    key.PEM, .NPMRC и явный src/private.key продолжают скрываться.
11. **P2: размер после маскирования.** Reports повторно проверяет events/fail
    payload и checkpoint после sanitize до изменения task/history. Регрессии
    отправляют допустимый исходный payload, разрастающийся после маскирования:
    обе ручки дают 422. Существующие проверки result/publication merge сохранены.

Проверки:

- Runner: `cd runner && ./.venv-recheck/bin/pytest -q -rs` — 354 passed.
- Server: `cd server && ./.venv-recheck/bin/pytest -q -rs` — 788 passed, 1 skipped.
- Пропуск прежний: FOR UPDATE SKIP LOCKED требует PostgreSQL TEST_DATABASE_URL;
  прогон использует SQLite. PostgreSQL concurrency не проверена.
- Добавлены 28 Python cases runner, 27 server; 5 Go test functions / 7 scenarios.
- Первичный RED-прогон до исправлений: 22 failed / 1 passed runner,
  17 failed / 2 passed server; воспроизведены все пункты 1–11.
- **Go и gofmt отсутствуют:** build, go test, форматирование и RED-прогон Go
  не запускались, Go-код проверен чтением. Это остаётся непроверенным.
- `git diff --check` — чисто. Все изменённые/добавленные файлы ≤150 строк.
  Прежние длинные файлы вне задачи не менялись. Секреты не добавлялись;
  credential-фикстуры синтетические, локальные config/SSH markers инертные.
- Project-memory status/update: not_initialized; индекс обновить невозможно
  без инициализации. Память проекта вне задачи не создавалась.

Обновлены SECURITY.md, deploy/README.md, runner/SECURITY.md, runner/GIT_CONTRACT.md,
JSON-контракт Git claims и этот отчёт. Index conflict flags сохраняются сервером
только как agent_reported claims; новой серверной верификации они не предоставляют.
Миграция БД не нужна.
