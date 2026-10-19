# Tasks

Решения — `design.md` и D-40 (`docs/decisions.md`). Начинается после принятия `mvp-06-sandbox-runtime`.

## 1. Общий протокол

- [ ] 1.1 Перенести `SandboxProvider`, `ExecResult`, ошибки и `FakeSandbox` в `adapters/sandbox/`, реэкспорт из `adapters/novita`, импорты сервисов на `adapters.sandbox` — проверка: все тесты mvp-06 зелёные без изменения логики

## 2. Конфигурация и выбор

- [ ] 2.1 `config.py`: `SandboxConfig.provider`, `VpsConfig` (`host`, `port`, `user`, `host_fingerprint` `^SHA256:[A-Za-z0-9+/]{43}$`), валидатор «vps требует блок»; `settings.py`: `vps_ssh_private_key: SecretStr | None`; `config/harness.example.yaml` — проверка: `test_config.py`, `test_settings.py`
- [ ] 2.2 `wiring.build_sandbox_provider` и проверка секрета выбранного провайдера при старте worker и CLI — проверка: тест «Нет ключа SSH»

## 3. Адаптер VPS

- [ ] 3.1 `asyncssh` (точная версия) в `apps/server/pyproject.toml`, `uv lock`; при отсутствии типов — override mypy с комментарием — проверка: mypy
- [ ] 3.2 `adapters/vps/client.py` `SshSandboxProvider`: соединение с кешем и переоткрытием, проверка отпечатка, exec с env через stdin, SFTP, no-op `pause`/`extend_timeout`, маппинг ошибок — проверка: `test_vps_client.py` против локального тестового SSH-сервера `asyncssh` (in-process, ключи генерируются в тесте): «Чужой ключ хоста», «Секрет не виден в списке процессов» (значение нет в принятой команде), ненулевой код → `ExecResult`, нет файла → `None`
- [ ] 3.3 `test_vps_live.py` (`-m live`, `LIVE_VPS_HOST`, `LIVE_VPS_USER`, `LIVE_VPS_FINGERPRINT`, `LIVE_VPS_SSH_KEY`): exec, write/read, фоновый процесс переживает переподключение — проверка: вручную, владелец

## 4. Bootstrap и документация

- [ ] 4.1 `deploy/sandbox/bootstrap.sh`: проверка `git`, `node` ≥ 18, `npm`, `setsid` (код 3), `npm prefix ~/.npm-global` без sudo; `run.sh` и команды сервера дополняют `PATH` — проверка: shellcheck; тест «Bootstrap без нужных программ» на фейке; двойной запуск на VPS — владелец
- [ ] 4.2 `docs/deployment.md` (подготовка VPS: пользователь без sudo, ключ с `from=`, отпечаток `ssh-keyscan | ssh-keygen -lf -`), ARCHITECTURE.md §2/§9, `.env.example`, PLAN.md, `apps/server/README.md` — проверка: ревью

## 5. Память проекта

- [ ] 5.1 `memory_update` по изменённым путям, `memory_annotate` для каждого нового и изменённого файла, `memory_status` без устаревших файлов
