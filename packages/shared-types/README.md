# Общие типы проектов

Единственный источник контракта — `shared/src/harness_shared/projects.py`.
`export_schema.py` экспортирует JSON Schema моделей `ProjectInput`, `ProjectUpdate`
и `ProjectRead`, включая `ProjectRepo` и `ProjectStatus`; `generate.mjs` преобразует
её через `json-schema-to-typescript`. Сгенерированный `src/projects.ts` хранится в git.

Установка инструментов и команды из `apps/console`:

```sh
pnpm install --frozen-lockfile
pnpm types:generate
pnpm types:check
```

Требуется Python с Pydantic v2. Необязательная переменная: `PYTHON`.
Проверка повторяемости `types:check` не изменяет файлы. Отдельного runtime,
сетевого клиента и ручных копий типов в пакете нет.
