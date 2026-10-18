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
