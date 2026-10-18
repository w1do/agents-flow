# AGENTS.md

Правила для Codex и других агентов совпадают с [CLAUDE.md](CLAUDE.md) — читай его первым.
Кратко: работа только по изменению в `openspec/changes/<id>/tasks.md`; бизнес-логика в `services/`;
внешние API через `adapters/`; схема БД только миграциями; секреты не в коде, логах и git;
каждое изменение кода с тестами и `./tools/harness check`; ARCHITECTURE.md и PLAN.md обновляются тем же изменением.
