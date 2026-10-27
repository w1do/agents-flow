from sqlalchemy import exists, select

from app.models.user import User
from app.repositories.base import Repository


class UserRepository(Repository[User]):
    model = User

    def has_users(self) -> bool:
        return bool(self.session.scalar(select(exists().where(User.id.is_not(None)))))

    def by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))
