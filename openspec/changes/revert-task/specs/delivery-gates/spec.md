## ADDED Requirements

### Requirement: Откат через те же гейты

`revert_task` SHALL создавать revert-коммит в новой ветке и проходить те же гейты, что обычная задача; без `confirm=true` MUST возвращать `confirm_required`.

#### Scenario: Откат

- **WHEN** оператор вызывает `revert_task` с подтверждением для влитой задачи
- **THEN** создаётся задача отката с MR, гейты пройдены
