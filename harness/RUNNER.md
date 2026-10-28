# Контракт внешнего runner

Harness запускает `runner.command` через служебный supervisor того же бинарника,
без интерпретации shell-строки.
Запускайте harness от непривилегированной учётной записи. Runner наследует её UID;
supervisor включает Linux `no_new_privs`, поэтому setuid-бинарники и `sudo` не
поддерживают повышение привилегий.
Один запуск обслуживает один этап: planning, implementation, testing, publication.
CWD, `path` и `worktree` указывают на изолированную рабочую копию задачи.
Относительный путь к исполняемому файлу разрешается от workspace_path;
имя без `/` ищется в PATH. Аргументы передаются без подстановок.

Runner читает один JSON-объект из stdin и пишет NDJSON в stdout:

```json
{
  "task": {"id": "task-id", "title": "Task", "description": "Description"},
  "stage": "planning",
  "path": "/projects/project-task-task-id",
  "worktree": "/projects/project-task-task-id",
  "branch": "task/task-id",
  "read_only": true,
  "checkpoint": null,
  "skills": [{"category": "development", "filename": "development--one.md", "content": "Instructions"}]
}
```

`task` также может содержать project_id, source_type, source_text, status, plan_text.
Исходный task.checkpoint обнуляется: сохранённый checkpoint runner передаётся
отдельным полем. Вход реализации и проверок содержит plan_text, при доработке —
feedback. `result_data` передаёт накопленный результат предыдущего этапа.

Testing и publication требуют настоящий Git worktree в ветке `task/<task_id>`.
Testing возвращает `result_data.base_sha`, фактические `changed_paths` и
`verification`: `base_sha`, `head_sha`, `commits` (строки `sha subject`),
`status_porcelain` (строка с переводами строк), `diff_name_only` (массив путей),
`worktree_clean`. `diff_name_only` — tracked diff от base до текущего worktree;
untracked-файлы отражены в status и changed_paths. Base берётся из предыдущего
result_data, при первом testing — из HEAD до команд. Harness сохраняет эти
данные для publication. Сервер хранит их в существующем JSON result_data;
старый result без verification разрешён с событием `verification_missing`.

После успешных publication-команд trusted runner вне sandbox выполняет
`git add -A -- <пути>` и `git commit -m "task(<task_id>): <title>"`.
Разрешения задаются в тексте publication skill строкой
`allowed_paths: ["src/", "README.md"]` либо полем skill.allowed_paths.
Файл разрешается точно, каталог — префиксом с `/`, `.` разрешает дерево.
Без декларации изменённые пути запрещены. `.env*`, `.git`, `.secrets`, token
и recovery/временные артефакты запрещены всегда; symlink/hardlink тоже запрещены.
Git hooks и fsmonitor при host-операциях отключены. Git-диагностика не логируется.
Результат содержит `commit_sha`, `commit_subject`, реальные `changed_paths`,
`base_sha` и свежую verification. При отсутствии изменений: success=true,
commit_sha=null, commit_subject=null, changed_paths=[], no_changes=true.
Ошибка Git даёт success=false и result_data.code=`git_<reason>`.
Publication payload обновляет result_data задачи, включая коммит и verification.

В planning runner обязан соблюдать read_only и не менять файлы. Это контракт
runner, а не файловая песочница. Harness не выполняет команды проекта сам.
Для planning/implementation передаются непубликационные skills, для testing —
test/testing, для publication — git/deploy. Категория берётся из category или
префикса filename/name. Skills публикации передаются только после подтверждённого
сервером publish (merged + publication_requested).

События (каждое — отдельная строка, максимум 1 МиБ):

```json
{"type":"plan","plan_text":"Human-readable plan"}
{"type":"progress","message":"Work in progress","payload":{"step":1},"checkpoint":{"cursor":"saved"}}
{"type":"test_result","command":"command from a skill","exit_code":0,"summary":"passed"}
{"type":"result","result_summary":"Implemented","result_data":{"changed_paths":["file"]}}
{"type":"failure","message":"Runner failure","checkpoint":{"cursor":"saved"}}
```

Planning завершается ровно одним plan, остальные этапы — одним result и exit 0.
Для publication result содержит обязательный `success: true|false`, message и
необязательный result_data с итогом публикации. Последующий ненулевой exit всё
равно считается сбоем: промежуточное terminal-событие не подтверждается заранее.

Checkpoint — JSON-объект произвольного содержания; он сохраняется немедленно
локально и через events до продолжения обработки событий. На сервер передаётся
обёртка `{harness:{stage,worktree,plan_text,...},runner:<checkpoint>}`;
при восстановлении runner получает только своё содержимое. Checkpoint предыдущего
этапа передаётся следующему запуску, включая повтор после отмены.

Harness агрегирует test_result в result_data.tests, объединяя данные реализации
и проверок. Произвольный progress payload помещается в payload.details отчёта:
runner не может задавать серверный статус через payload.status.

Неправильный JSON, неизвестный тип, повтор terminal-события, отсутствие terminal,
failure и ненулевой exit вызывают fail. Содержимое stderr и сырые ошибки запуска
не выводятся. AGENTS_FLOW_INIT_TOKEN и AGENTS_FLOW_AGENT_TOKEN не наследуются.
Agent-токен не передаётся через JSON или аргументы процесса.

До каждого этапа проверяется execution-state с актуальным lease_id. Пока ждём
решение, runner не работает. Approved разрешает реализацию, rework повторяет её
с feedback, keep_ready продолжает ожидание без публикации; отсутствие отдельного
result_decision в ответе тоже оставляет ready в ожидании. Для publish проверяется
publication_requested, для rework — переход обратно в active.

Ожидание ограничено таймаутом и контекстом отмены. Отклонение плана повторяет planning
с feedback, корзина останавливает run без fail. API не предоставляет ручку освобождения аренды;
Harness не имитирует такое освобождение другим отчётом. При keep_ready heartbeat
продолжается, пока не пришло следующее решение, сигнал или таймаут ожидания.

При 409 runner и его группа процессов немедленно останавливаются. Ни fail, ни
новые отчёты по потерянной аренде не отправляются. При сетевой ошибке сохраняется
тот же отчёт и повторяется с тем же event_id/Idempotency-Key, включая перезапуск.
Сохранённые файлы worktree не удаляются и не откатываются.

Чтение stdout отделено от обработки событий очередью с backpressure. После
завершения runner читается настоящий EOF; таймера принудительного закрытия нет.
Ошибки чтения, включая неожиданное закрытие, являются ошибкой протокола.
JSON-числа сохраняют точное представление на всех границах через UseNumber.

На Linux supervisor устанавливает PR_SET_CHILD_SUBREAPER до запуска runner,
а также запрещает runner повышать привилегии через PR_SET_NO_NEW_PRIVS,
обрабатывает SIGCHLD и забирает осиротевших потомков, включая double-fork/setsid.
Перед выходом он убивает и reap'ит всех своих детей. Это отдельный процесс:
его wait не затрагивает дочерние процессы других задач/приложений. EOF служебного
канала запускает очистку и при аварийном выходе самого harness. Периодического
опроса дерева процессов нет. Нужен доступ к `/proc/self/task/*/children`.
Альтернатива cgroup даёт наследуемую группу и group kill, но требует делегированной
иерархии с правом записи; subreaper работает без такой настройки.
Если механизм недоступен, runner не запускается. Иные ОС отклоняют run до claim.

Полные claim и runtime-state хранятся вне ограниченного journal, в приватных
snapshot-файлах служебного Git-каталога. Содержимое входа не обрезается из-за размера
journal; snapshot ограничен 64 МиБ (лимит ответа API — 16 МиБ). Запись создаёт новый
файл и атомарно заменяет запись в закреплённом каталоге. Старый общий inode не
открывается для записи; это правило применяется также к обновлению skills.

Секреты маскируются в значениях и именах JSON-полей. Учитываются форматы ключей,
известный agent-токен и его URL/base64/hex/Unicode/HTML-представления. Коллизии
очищенных имён сохраняют все значения под детерминированными суффиксами.

Heartbeat `409 Task is finished` при существующем финальном pending означает
ожидание подтверждения: никакая новая работа не запускается, повторяется только
прежний отчёт. Его 200 подтверждает завершение, его 409 прекращает работу. Другие
heartbeat-конфликты сразу останавливают задачу. Тела ошибок сервера не сохраняются:
извлекается только разрешённая классификация Task is finished.

Сбой публикационного runner передаётся через publication-result с success=false:
сервер сохраняет merged и освобождает аренду.
