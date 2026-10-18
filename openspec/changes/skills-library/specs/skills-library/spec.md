## ADDED Requirements

### Requirement: Манифест skills workspace

`skills_manifest` SHALL возвращать skills только workspace задачи с именем, описанием, версией и хешем.

#### Scenario: Обновлённый skill

- **WHEN** оператор обновил skill workspace
- **THEN** следующий `skills_manifest` агента показывает новую версию

### Requirement: Применение со следующего этапа

Новая версия skill SHALL применяться агентом со следующего этапа; текущий этап MUST дорабатываться со старой.

#### Scenario: Обновление посреди этапа

- **WHEN** skill обновлён во время этапа
- **THEN** агент берёт новую версию после следующего `report_task`
