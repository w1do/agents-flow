from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Skill, SkillCategory
from app.schemas.skills import CategoryCreate, SkillCreate
from app.services.skills import category_save, skill_save

CATEGORIES = (
    ("Разработка", "Создание и изменение приложений"),
    ("Ресёрч", "Исследование и подбор решений"),
    ("Тестирование", "Проверка качества и регрессий"),
    ("Git", "Публикация изменений в Git"),
    ("Деплой", "Развёртывание приложений"),
    ("Документация", "Инструкции и отчёты"),
)

STARTER_SKILLS = (
    ("Разработка", "landing", "Создание лендинга", """# Создание лендинга
1. Изучи требования, структуру проекта и инструкции репозитория.
2. Согласуй план и критерии готовности; следуй существующим компонентам и стилю.
3. Реализуй адаптивную страницу и проверь доступность элементов управления.
4. Выполни предусмотренные проектом проверки, укажи результат в отчёте.
При ошибке останови зависимые действия и опиши причину и следующий шаг.
Не меняй секреты, инфраструктуру и посторонние файлы. Не выполняй push или deploy.
Готово: требования выполнены, проверки успешны, изменения описаны.
"""),
    ("Тестирование", "frontend", "Проверки интерфейса", """# Проверки интерфейса
1. Найди команды lint, тестов и сборки в документации и package.json проекта.
2. Выполни доступные проверки, проверь основные сценарии и адаптивность.
3. Зафиксируй команды, коды завершения и воспроизводимые шаги ошибок.
При сбое сообщи причину; не объявляй непроверенный результат успешным.
Не меняй продуктовый код, конфигурацию, секреты или эталонные снимки без задачи.
Готово: проверки пройдены или каждый блокер явно описан. Не выполняй публикацию.
"""),
    ("Git", "github-push", "Публикация в GitHub после publish", """# Публикация в GitHub
1. Требуй явное решение пользователя publish для текущей задачи.
2. До publish разрешены только просмотр diff, статуса и результатов проверок.
3. После publish проверь ветку и remote, исключи секреты и посторонние изменения.
4. Создай коммит только с файлами задачи и выполни обычный push в согласованную ветку.
При ошибке остановись и сообщи её; не используй force push и не меняй чужие коммиты.
Не меняй секреты, remote, защищённые ветки или настройки репозитория.
Готово: публикация подтверждена результатом Git; сообщи ветку и идентификатор коммита.
"""),
    ("Деплой", "dokploy", "Развёртывание в Dokploy после publish", """# Развёртывание в Dokploy
1. Требуй явное решение пользователя publish и согласованную целевую среду.
2. До publish изучи инструкции проекта, конфигурацию и результаты проверок.
3. После publish убедись в наличии резервной копии БД и секретов в Environment.
4. Разверни согласованную версию по инструкции проекта, дождись миграций и healthcheck.
5. Проверь публичный адрес и сообщи версию и результат проверки.
При сбое остановись и следуй согласованному плану восстановления; сохрани данные БД.
Не меняй секреты, домены, сеть или чужие сервисы. Не откатывай схему БД вручную.
Готово: целевая версия развёрнута и healthcheck успешен.
"""),
)


def seed_skills(session: Session) -> str:
    # Serialize repeatable seeds, including competing console processes.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7319042282)"))
    elif session.get_bind().dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    categories = {}
    created_categories = created_skills = 0
    for order, (name, description) in enumerate(CATEGORIES):
        category = session.scalar(select(SkillCategory).where(SkillCategory.name == name)
                                  .order_by(SkillCategory.id).limit(1))
        if category is None:
            category = category_save(session, CategoryCreate(
                name=name, description=description, sort_order=order,
            ))
            created_categories += 1
        categories[name] = category.id
    for category, name, description, content in STARTER_SKILLS:
        category_id = categories[category]
        existing = session.scalar(select(Skill.id).where(
            Skill.category_id == category_id, Skill.name == name,
        ).limit(1))
        if existing is None:
            skill_save(session, SkillCreate(category_id=category_id, name=name,
                                           description=description, content=content))
            created_skills += 1
    return f"Created {created_categories} categories and {created_skills} starter skills."
