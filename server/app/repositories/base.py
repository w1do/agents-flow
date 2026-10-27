from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.base import Base

Model = TypeVar("Model", bound=Base)


class Repository(Generic[Model]):
    model: type[Model]

    def __init__(self, session: Session):
        self.session = session

    def create(self, **values: Any) -> Model:
        instance = self.model(**values)
        self.session.add(instance)
        self.session.flush()
        return instance

    def get(self, entity_id: UUID) -> Model | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100, **filters: Any) -> list[Model]:
        if offset < 0 or limit < 1:
            raise ValueError("offset >= 0, limit >= 1")
        statement = select(self.model).filter_by(**filters)
        statement = statement.order_by(self.model.id).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def update(self, instance: Model, **values: Any) -> Model:
        for key in values:
            if key == "id" or key not in self.model.__mapper__.column_attrs:
                raise ValueError(f"Недопустимое поле: {key}")
        for key, value in values.items():
            setattr(instance, key, value)
        self.session.flush()
        return instance

    def delete(self, instance: Model) -> None:
        self.session.delete(instance)
        self.session.flush()
