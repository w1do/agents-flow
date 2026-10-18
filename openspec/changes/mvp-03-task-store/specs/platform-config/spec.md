## ADDED Requirements

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
