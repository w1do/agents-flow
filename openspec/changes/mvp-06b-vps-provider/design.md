# Design: mvp-06b-vps-provider

## Context

`mvp-06` сделал рантайм песочницы над Protocol `SandboxProvider` (`connect`, `exec`, `write_file`, `read_file`,
`pause`, `extend_timeout`), сейчас он лежит в `adapters/novita/protocol.py`. Сервисы (`services/sandboxes.py`),
worker и CLI зависят только от протокола. Раскладка в песочнице — `~/.harness/{bin,tasks,worktrees}`, `~/work`,
агент запускается через `setsid nohup bash run.sh` (D-35…D-38).

## Goals / Non-Goals

**Goals:** тот же рантайм на VPS по SSH без изменений в сервисах; выбор провайдера одной строкой конфига; ключ
только в ENV; секреты команды не видны в списке процессов VPS; хост проверяется по закреплённому отпечатку.

**Non-Goals:** пул, выбор провайдера на задачу, Docker, установка системных пакетов на VPS.

## Decisions

1. **Общий протокол.** `adapters/novita/{protocol,errors}.py` и `FakeSandbox` переносятся в
   `adapters/sandbox/`; `adapters/novita/__init__.py` реэкспортирует имена, чтобы импорты mvp-06 не ломались
   (затем импорты в сервисах переводятся на `adapters.sandbox`). Поведение протокола не меняется.
2. **SSH-клиент — `asyncssh`** (нативный async, типизирован, есть SFTP), точная версия в `apps/server/pyproject.toml`.
   Альтернатива `paramiko` синхронная (нужен `to_thread`), `ssh` через subprocess — ключ пришлось бы класть на диск.
   Ключ из `VPS_SSH_PRIVATE_KEY` (PEM/OpenSSH, `SecretStr`) импортируется в память (`asyncssh.import_private_key`),
   на диск сервера не пишется. Ключ с паролем не поддерживается в MVP.
3. **Проверка хоста.** `sandbox.vps.host_fingerprint` (`SHA256:…`, как у `ssh-keygen -lf`) обязателен; ключ хоста
   сравнивается с ним, при несовпадении — `SandboxUnavailable("host_key_mismatch")`, команда не выполняется.
   TOFU и `known_hosts=None` запрещены.
4. **Семантика методов:**
   - `connect(sandbox_id)` — открыть (или переиспользовать) SSH-соединение и выполнить `true`; соединение
     кешируется в адаптере и переоткрывается при обрыве. Недоступен хост или отказ аутентификации →
     `SandboxUnavailable` (`unreachable` / `auth_failed`); `SandboxNotFound` у VPS не бывает.
   - `exec(cmd, envs, cwd, timeout_s)` — `bash -lc` с `cd` в `cwd`; ненулевой код → `ExecResult`, как у Novita;
     таймаут → `SandboxUnavailable("timeout")`.
   - `write_file`/`read_file` — SFTP; нет файла → `None`. Права новых файлов 0600, каталогов — 0700.
   - `pause`, `extend_timeout` — пустые операции с записью в лог на DEBUG: VPS всегда включён и не удаляется по
     таймауту. Статус песочницы в БД (`paused` = свободна) сохраняет смысл.
   - `sandbox_id` для VPS — `provider_id` из конфига (логическое имя, например `vps-main`); адаптер работает с
     одним хостом из `sandbox.vps`.
5. **Секреты не в argv.** Значения `envs` передаются через stdin: удалённая команда —
   `bash -c 'while IFS= read -r -d "" kv; do export "$kv"; done; cd "$1" && exec bash -c "$2"' _ <cwd> <cmd>`,
   stdin — `KEY=VALUE\0…`. Имена ключей проверяются (`^[A-Z_][A-Z0-9_]*$`), значения с NUL отклоняются. Так
   значения не попадают в `ps`, `/proc/<pid>/cmdline` и журнал sshd. `AcceptEnv`/`SendEnv` не используются:
   требуют правки `sshd_config` и root.
6. **Выбор провайдера.** `SandboxConfig.provider: Literal["novita", "vps"] = "novita"`, `SandboxConfig.vps:
   VpsConfig | None` (`host`, `port=22`, `user`, `host_fingerprint`); валидатор: `provider == "vps"` требует блок
   `vps`. Имена полей не содержат сегментов-секретов (D-20). `wiring.build_sandbox_provider(settings, config)`
   возвращает `NovitaSandboxProvider` или `SshSandboxProvider`; при `vps` без `VPS_SSH_PRIVATE_KEY` или при `novita`
   без `NOVITA_API_KEY` — ошибка конфигурации с именем переменной при старте worker и CLI.
7. **Изоляция (решение владельца).** Отдельный пользователь VPS без sudo (рекомендуется VPS только под агента),
   home 0700. Bootstrap не просит root: проверяет `git`, `node` ≥ 18, `npm`, `setsid` и выходит с кодом 3 и
   сообщением «нет <программы>»; `npm install -g` — в `~/.npm-global` (`npm config set prefix`), `PATH` дополняется
   в `run.sh` и командах сервера. Остаточный риск: агент с `bypassPermissions` имеет доступ ко всему, что доступно
   пользователю VPS, и к исходящей сети — как в Novita (D-18); на общем VPS это недопустимо, что указано в
   `docs/deployment.md`.
8. **Очистка и пауза.** Порядок `cleanup` → `pause` из mvp-06 остаётся; на VPS `pause` ничего не делает, поэтому
   свободная песочница = строка `paused` без `current_task_id`. Процессы агента после завершения не остаются:
   `cleanup` проверяет `kill -0` по pid и при живом процессе убивает группу.

## Risks / Trade-offs

- [Ключ SSH в ENV даёт полный доступ к пользователю VPS] → пользователь без sudo, отдельный ключ только для харнесса,
  `from="<ip сервера>"` в `authorized_keys` (рекомендация в docs), ротация как у OAuth-токена.
- [Агент на VPS может читать `/proc/<pid>/environ` своих процессов] → принято: агент и так получает токены.
- [Обрыв SSH во время долгой команды] → долгое — только фоновый `run.sh` (mvp-06), exec короткие; соединение
  переоткрывается.
- [Разные версии node/git на VPS] → bootstrap проверяет минимальные версии и печатает их в `profile_version`.
