# platform-config Specification

## Purpose
Проверка и загрузка конфигурации платформы: ENV (`settings.py`), файл `harness.yaml` (`config.py`) и запуск
сервера и worker с отказом при невалидной конфигурации. Сообщения об ошибках не раскрывают значения секретов.

## Requirements

### Requirement: Проверка конфигурации при старте

Сервер и worker SHALL проверять ENV и файл `harness.yaml` до начала работы и MUST завершаться с ненулевым
кодом и понятным сообщением, если обязательное значение отсутствует или конфиг невалиден.
Сообщение об ошибке MUST NOT содержать значения секретов.

#### Scenario: Нет обязательной переменной

- **WHEN** сервер запускается без `TELEGRAM_BOT_TOKEN`
- **THEN** процесс завершается с ненулевым кодом, а в выводе указано имя переменной без значений других переменных

#### Scenario: Секрет в YAML

- **WHEN** в `harness.yaml` есть поле `gitlab_token`
- **THEN** проверка конфигурации отклоняет файл с указанием поля

#### Scenario: Валидный конфиг

- **WHEN** выполнена команда `harness-server check-config` с корректными ENV и YAML
- **THEN** команда выводит список workspace и завершается с кодом 0

### Requirement: Описание workspace в конфиге

Конфиг SHALL описывать хотя бы один workspace с полями: `id`, `name`, `voice_aliases`, `gitlab_project`,
`default_branch`, `test_command` (может отсутствовать), `agent`. Идентификаторы workspace MUST быть уникальны.

#### Scenario: Повтор идентификатора

- **WHEN** два workspace имеют одинаковый `id`
- **THEN** конфиг отклоняется с указанием повторяющегося `id`

### Requirement: Проверки живости и готовности

Сервер SHALL отвечать `200` на `GET /health` без обращения к внешним системам и на `GET /health/ready`
только когда база данных доступна; иначе `GET /health/ready` MUST отвечать `503`.

#### Scenario: БД недоступна

- **WHEN** Postgres остановлен
- **THEN** `GET /health` отвечает `200`, а `GET /health/ready` отвечает `503`

### Requirement: Секреты и учётные данные в конфигурации

Проверка `harness.yaml` SHALL отклонять ключи с сегментами `token`, `tokens`, `key`, `password`, `passwd`, `pwd`,
`secret`, `secrets`, `apikey`, `credential`, `credentials` на любом уровне вложенности и MUST отклонять
`gitlab.base_url` с учётными данными в адресе (`user@host`, `user:pass@host`). Переменная `HARNESS_ADMIN_TOKEN`,
если задана, MUST быть не короче 32 символов. Сообщения об ошибках MUST называть поле или переменную без значения.

#### Scenario: Пароль в адресе GitLab

- **WHEN** в `harness.yaml` указан `gitlab.base_url: https://user:pass@gitlab.example.com`
- **THEN** проверка конфигурации отклоняет файл с указанием `gitlab.base_url`, а значение пароля в сообщении отсутствует

#### Scenario: Новый сегмент секрета

- **WHEN** в `harness.yaml` есть поле `gitlab_pwd`
- **THEN** проверка конфигурации отклоняет файл с указанием поля

#### Scenario: Короткий операторский токен

- **WHEN** сервер запускается с `HARNESS_ADMIN_TOKEN` короче 32 символов
- **THEN** процесс завершается с ненулевым кодом, в выводе есть имя переменной и нет её значения

### Requirement: Миграции не отключают логирование приложения

Применение миграций в процессе приложения (`harness-server migrate`) SHALL сохранять активными уже созданные
логгеры приложения.

#### Scenario: Логгер после миграции

- **WHEN** логгер `harness_server.*` создан до вызова миграций до head
- **THEN** после миграций логгер не отключён
