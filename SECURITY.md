# Безопасность host Git и отчётов

Модель и содержимое worktree недоверенные. Hooks, filters, fsmonitor, GPG и
transport-программы из конфигурации репозитория не должны запускаться на хосте.

- Перед каждой Git-командой runner/harness читают `git config --list --show-origin
  --includes --null` для всех областей, включая system/global/local/worktree.
  При включённом `extensions.worktreeConfig` дополнительно перечисляют `--worktree`.
  Вложенные includes участвуют в обнаружении драйверов; `include.path` не становится
  переопределением безопасности. Это учитывает смену конфигурации после skills.
- Рабочие команды отключают system/global config и наследуемые Git overrides;
  clean/smudge заменены на cat, process отключён, required=false. Hooks, fsmonitor,
  GPG, external diff и textconv нейтрализованы явными `-c`, независимо от includes.
  `core.excludesFile=/dev/null` и `status.showUntrackedFiles=all` сохраняют видимость
  untracked; собственные `.gitignore` репозитория продолжают действовать.
- Все вызовы получают `GIT_NO_LAZY_FETCH=1`, `core.sshCommand=/bin/false` и
  `protocol.file.allow=never`; прочие transport-протоколы также запрещены.
  Harness `gitrepo.Clone(..., allowLocal=true)` отдельно разрешает локальный remote
  только для clone без checkout. Чтение истории не получает этого разрешения.
- Staging, проверка путей/типов/blob и commit используют одну приватную копию индекса.
  После успеха runner получает реальный `index.lock`, сравнивает индекс с исходными
  байтами и атомарными rename устанавливает проверенную копию. При занятом lock или
  расхождении чужие изменения сохраняются; публикация успешна, verification содержит
  `index_conflict=true`, `stale_index=true`. `worktree_clean` всегда проверяет реальный
  индекс относительно HEAD и worktree, включая untracked.
- **Эксплуатационное требование: внутри worktree не должно быть mount-point'ов**, в том
  числе bind-mount на том же устройстве. Проверки st_dev и `/proc/self/mountinfo`
  отклоняют известные вложенные mount-point'ы с `mount_crossing`, включая listing,
  чтение/запись, сбор артефактов и проверку commit paths. Mountinfo должен быть доступен
  и отражать namespace runner. Процесс не получает права менять mounts; привилегированный
  конкурент, создающий mount после проверки, остаётся вне модели угроз.
- Защищённые компоненты сравниваются через casefold. Текстовая политика скрывает весь
  токен пути вместе с query/fragment-хвостом до пробела, кавычки, `,` или `;`.
  Идентификаторы `KeyboardEvent.key`, `event.key` и обращения `.key` без контекста пути
  сохраняются; явно переданные файловые пути проверяются строгой компонентной политикой.
  Защищённый `event_id` отклоняется с 422. Логи ошибок используют серверный sanitizer
  без сырого traceback/exception text.
- Report payload/result_data ≤256 КиБ компактного UTF-8 JSON до и после маскирования;
  объединённый publication result_data тоже ограничен. Вложенность payload/checkpoint
  ≤32; проверка структуры тела предшествует JSON parsing. Тело report ≤512 КиБ,
  включая chunked и reverse-proxy root_path. Нарушения дают 422 без исходного payload.
  Git-утверждения сохраняются только как `agent_reported`, включая флаги конфликта индекса.

Подробности sandbox, redaction и остаточных рисков: [runner/SECURITY.md](runner/SECURITY.md).

## Известные ограничения группы 12

- **Гонка HEAD.** Враждебный внешний писатель между чтением `head_sha` и `log`
  может дать несогласованную `verification` при `success: true`
  (`runner/runner/git_facts.py`). Нужен эксклюзивный worktree, см.
  [runner/SECURITY.md](runner/SECURITY.md).
- **Управляющее исключение.** Резервный 500 в
  `server/app/middleware/security_headers.py` теряет тип
  `SystemExit`/`KeyboardInterrupt`; утечки секрета нет.
- **Подавление диагностики.** После коммита часть ошибок не поднимается
  намеренно: `success: true` не доказывает исправность индекса, сбой виден по
  флагам `cleanup_failed` / `stale_index` / `index_conflict`.
- **Go не проверен запуском.** Тулчейна нет в системе; правки `harness/`
  проверены только чтением кода и статически.

Решение и проверки: [docs/decisions/2026-10-28-agents-flow-mvp-group-12.md](docs/decisions/2026-10-28-agents-flow-mvp-group-12.md).
