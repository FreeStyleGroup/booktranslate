"""Контекст запроса: от чьего имени и в какой организации идёт работа.

Живёт в слое сервисов, а не в зависимостях FastAPI, потому что нужен и
фоновым задачам, и консольным командам: у них тоже есть организация, от
имени которой они действуют, но нет HTTP-запроса.
"""

import uuid
from dataclasses import dataclass

from app.models.organization import Role, User
from app.services.errors import AccessDeniedError


@dataclass(frozen=True)
class RequestContext:
    user: User
    organization_id: uuid.UUID
    role: Role

    def require(self, *roles: Role) -> None:
        """Проверка права на действие.

        Владелец не перечисляется в каждом вызове: он может всё в своей
        организации по определению, и забытый в списке OWNER выглядел бы
        как отказ владельцу в его собственных данных.
        """
        if self.role is not Role.OWNER and self.role not in roles:
            raise AccessDeniedError("Недостаточно прав для этого действия")
