# Proposal: mvp-06b-vps-provider

> Второй провайдер песочницы — обычный VPS по SSH. Решение владельца 2026-10-19 (D-40): в MVP, сразу после
> `mvp-06-sandbox-runtime`.

## Why

Novita — не единственное место, где можно запускать агента. У владельца есть VPS: там нет квоты vCPU, таймаута
уничтожения и оплаты хранения паузы. Для VPS нужна по сути только привязка SSH-ключа, остальное — тот же
рантайм: bootstrap, `~/.harness`, worktree, фоновый `claude -p`, `status.json`.

## What Changes

- Протокол песочницы становится общим: `adapters/sandbox/{protocol,errors,fake}.py` (`SandboxProvider`,
  `ExecResult`, `SandboxNotFound`, `SandboxUnavailable`, `FakeSandbox`); `adapters/novita` реализует его и
  реэкспортирует прежние имена.
- Новый адаптер `adapters/vps` (`SshSandboxProvider`) на `asyncssh`: exec, файлы (SFTP), проверка ключа хоста по
  закреплённому отпечатку; `pause` и `extend_timeout` — пустые операции (VPS всегда включён).
- Выбор провайдера: `sandbox.provider: novita | vps` в `harness.yaml`, блок `sandbox.vps` (`host`, `port`, `user`,
  `host_fingerprint`); ENV `VPS_SSH_PRIVATE_KEY` (секрет). Сборка — `wiring.build_sandbox_provider`.
- Секреты команды на VPS передаются через stdin, а не в аргументах (не видны в `ps` и логах sshd).
- `bootstrap.sh` работает на VPS без sudo: проверяет `git`, `node`, `npm`, `setsid` и падает с понятной
  причиной, если их нет.
- Документация: `docs/deployment.md` — подготовка VPS (отдельный пользователь без sudo, ключ, отпечаток хоста).

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `sandbox-runtime`: добавляются требования (ADDED): Выбор провайдера песочницы, Песочница на VPS.

## Impact

- Зависит от: `mvp-06-sandbox-runtime`.
- Зависимость: `asyncssh` (точная версия, D-40). ENV: `VPS_SSH_PRIVATE_KEY`. Конфиг: `sandbox.provider`,
  `sandbox.vps.*`.
- Сервисы, worker и CLI не меняются: они работают с `SandboxProvider`.
- Ссылки: ТЗ §9, §13; D-35, D-36, D-37.

## Не входит

- Несколько песочниц и выбор провайдера на задачу или агента (`sandbox-pool`): в MVP одна песочница, провайдер
  выбирается в конфиге.
- Docker-изоляция на VPS (решение владельца: отдельный пользователь).
- Создание VPS и установка системных пакетов (node, git) — вручную владельцем.
