## ADDED Requirements

### Requirement: Манифест skills workspace

`skills_manifest` SHALL возвращать skills и агентов Claude только workspace задачи с видом (`skill` | `agent`), именем,
описанием, версией и хешем.

#### Scenario: Обновлённый skill

- **WHEN** оператор обновил skill workspace
- **THEN** следующий `skills_manifest` агента показывает новую версию

### Requirement: Применение со следующего этапа

Новая версия skill SHALL применяться агентом со следующего этапа; текущий этап MUST дорабатываться со старой.

#### Scenario: Обновление посреди этапа

- **WHEN** skill обновлён во время этапа
- **THEN** агент берёт новую версию после следующего `report_task`

### Requirement: Агенты Claude с платформы

Агент, созданный владельцем на платформе, SHALL храниться и синхронизироваться тем же механизмом, что skill (вид
`agent`), и MUST раскладываться в песочнице в `~/.claude/agents/<name>.md`. Запись с frontmatter, где `name` не
совпадает с именем записи или нет `description`, MUST отклоняться.

#### Scenario: Новый агент на платформе

- **WHEN** оператор создал агента для workspace
- **THEN** следующий `skills_manifest` содержит запись вида `agent`, и со следующего этапа агент виден в песочнице
