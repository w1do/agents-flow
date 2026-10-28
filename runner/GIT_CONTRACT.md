# Коммит и проверка фактов

Testing и publication работают в Git worktree ветки `task/<task_id>`.
Команды skills получают приватную копию без Git и защищённых файлов.
Коммит выполняет host runner после успешных publication-команд;
без команд publication возвращает `success:false`.

Publication skill задаёт разрешения в content или поле skill.allowed_paths:

```text
allowed_paths: ["src/", "README.md"]
```

Разрешения объединяются: имя совпадает точно, завершающий `/` разрешает
каталог, `.` — дерево с обязательными исключениями. Без декларации изменения
запрещены. Удаления и обе стороны переименования проверяются одинаково.
В любом компоненте пути запрещены `.env*`, `.secrets`, `*.pem`, `*.key`,
`id_rsa*`, `.npmrc`, `.pypirc`, `*.env`, `.git`, `.agent-token`, `.runner-*`,
`runner-private-*`, `runner-backup-cleanup-*`. Symlink, hardlink, специальные
файлы, submodules и деревья индекса не публикуются. Сравнение защищённых имён — casefold;
другой st_dev или известный вложенный mount из `/proc/self/mountinfo`
отклоняется с `mount_crossing`. Внутри worktree не допускаются mount-point'ы.

Runner получает пути через `git status --porcelain=v1 -z --no-renames`,
читает обычные файлы через pinned descriptors, берёт режим из lstat/fstat
и пишет blob через `git hash-object --no-filters -w --stdin`.
`git update-index --add --cacheinfo` обновляет индекс без `git add`;
удаления и конфликты file/directory проходят `update-index --force-remove` до добавления.
При `core.filemode=false` режим берётся из индекса, сохраняя 100755 при правке содержимого.
После подготовки проверяются
режимы всех записей индекса через ls-files --stage --sparse (только 100644/100755), пути изменений
и staged blob. PEM private key, бинарь/NUL и известный секрет снимка
вызывают отказ `git_private_key`, `git_binary_blob`, `git_secret_blob`.
Пустой diff после подготовки — `success:true, commit_sha:null, no_changes:true`.

Git запускается с `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`,
`core.attributesFile=/dev/null`, `core.autocrlf=false`, `core.safecrlf=false`,
`core.fsmonitor=false`, `core.hooksPath=/dev/null`; локальные clean/smudge/process
драйверы отключаются также для status/diff. Коммит использует только
подготовленный приватный `GIT_INDEX_FILE`, `--no-verify`, без GPG-подписи и hooks.
Один файл используется для staging, проверки и commit. После успеха runner получает
реальный index.lock, сверяет исходные байты индекса и атомарными rename устанавливает
проверенную копию. Занятый lock или конкурентное изменение дают
verification.index_conflict=true, stale_index=true без отказа публикации и перезаписи
чужого индекса. Verification всегда проверяет реальный индекс, HEAD и worktree.
`log.showSignature=false`, `gpg.program=/bin/false`, `gpg.ssh.program=/bin/false`,
`diff.external=` действуют для всех команд; log/show используют `--no-show-signature`.
Перед каждой командой перечитываются все config scopes с --show-origin --includes,
включая явный --worktree при extensions.worktreeConfig. Внешние excludes отключены,
status.showUntrackedFiles=all; GIT_NO_LAZY_FETCH=1 и запрет transport-программ
действуют на все host-команды. Сырые Git-диагностика и аргументы команд не выводятся.

Runner возвращает `result_data.verification`:

- `base_sha`: исходный HEAD перед testing; проверенный SHA предка HEAD.
- `head_sha`: текущий HEAD.
- `commits`: только полные SHA из base..HEAD, без subject.
- `status`: массив `{code, path, ignored}`, например `{"code":"M","path":"src/a","ignored":false}`.
- `diff_name_only`: tracked-пути diff от base до worktree.
- `worktree_clean`: пуст ли status реального индекса, включая untracked-файлы.
- `index_conflict`, `stale_index`: true при невозможности безопасно обновить реальный индекс.

Защищённые пути заменяются `[REDACTED]`, команды с ними целиком маскируются.
Входные commit_sha/commit_subject/verification/claims очищаются на testing
и publication, включая ошибки. changed_paths вычисляется из Git заново.
Publication также возвращает `commit_sha`, `commit_subject`, `changed_paths`,
`no_changes`. Ошибки дают `success:false` и безопасный `result_data.code`.
Неудачный коммит сохраняет изменения и индекс; отката нет.

Сервер не имеет доступа к этому Git: входное verification сохраняется
только как `claims` с `source:"agent_reported"`, без использования для приёмки
или статуса. SHA — 40 hex/null, пути относительные и защищённые пути запрещены;
commits ограничен 100 SHA или объектами `{sha, subject}`. Неизвестные поля claims
отбрасываются. commit_sha сохраняется и без verification. changed_paths ≤1000,
commit_subject ≤200 символов; защищённые фрагменты subject и свободного текста скрываются.
Result_data/payload ≤256 КиБ компактного UTF-8 JSON, включая объединение publication payload
с прежним result_data и повторную проверку events/fail после маскирования.
Вложенность payload/checkpoint ≤32. Тело report ≤512 КиБ до JSON parsing, включая
chunked и root_path; иначе 422. Защищённый event_id также отклоняется.
