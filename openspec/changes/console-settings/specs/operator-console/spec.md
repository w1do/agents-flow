## ADDED Requirements

### Requirement: Настройки в базе

После импорта настройки workspace и агентов SHALL читаться из базы; `harness.yaml` MUST использоваться только для первичного импорта.

#### Scenario: Импорт

- **WHEN** сервер стартует с `harness.yaml` и пустыми таблицами настроек
- **THEN** workspace импортированы, дальнейшие правки — через консоль
