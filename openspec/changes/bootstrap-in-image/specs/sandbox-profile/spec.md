## ADDED Requirements

### Requirement: Скрипт bootstrap в образе сервера

Образ харнесса SHALL содержать скрипт `deploy/sandbox/bootstrap.sh`, читаемый пользователем `app`. Команда
`harness-server sandbox bootstrap` без `--script` MUST находить скрипт по пути от корня приложения, а не от текущего
каталога. Флаг `--script` MUST задавать другой путь, как раньше. Новая ENV для пути MUST NOT вводиться.

#### Scenario: Bootstrap из терминала Dokploy

- **WHEN** оператор в терминале контейнера `server` или `worker` (cwd `/`) запускает `harness-server sandbox bootstrap`
- **THEN** команда читает `/app/deploy/sandbox/bootstrap.sh` и не завершается ошибкой «не читается скрипт»

#### Scenario: Локальный запуск вне корня репозитория

- **WHEN** `harness-server sandbox bootstrap` запускается без `--script` из каталога вне репозитория
- **THEN** используется `deploy/sandbox/bootstrap.sh` из корня репозитория, bootstrap выполняется

#### Scenario: Явный путь

- **WHEN** команда запускается с `--script <путь>`
- **THEN** читается указанный файл, при недоступном файле — код 1 и «Ошибка: не читается скрипт <путь>»
