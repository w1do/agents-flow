## ADDED Requirements

### Requirement: Учёт по итогам сессии

После завершения агента система SHALL сохранять токены и стоимость сессии и отдавать суммы по периоду и workspace через `usage(period)`.

#### Scenario: Расход за день

- **WHEN** за день выполнены две задачи
- **THEN** `usage(day)` возвращает сумму двух сессий по workspace
