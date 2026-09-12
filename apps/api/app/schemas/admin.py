"""Схемы управления доступом."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.organization import Role, UserStatus


class AdminMembershipPublic(BaseModel):
    """Участие в пространстве — с ролью, которую администратор может сменить."""

    organization_id: uuid.UUID
    organization_name: str
    role: Role


class AdminUserPublic(BaseModel):
    """Пользователь в списке администратора."""

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    status: UserStatus
    is_superuser: bool

    # Когда зарегистрировался и когда последний раз входил: по первому
    # разбирают заявки, по второму — чистят список.
    created_at: datetime
    last_login_at: datetime | None

    # Кто и когда менял состояние доступа.
    status_changed_at: datetime | None
    status_changed_by: str | None

    memberships: list[AdminMembershipPublic]


class UserUpdate(BaseModel):
    """Правка учётной записи. Присылается только то, что меняется."""

    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=200)


class MembershipRoleChange(BaseModel):
    role: Role


class UserCounts(BaseModel):
    """Сколько учётных записей в каждом состоянии."""

    pending: int
    active: int
    suspended: int


class UserListPublic(BaseModel):
    items: list[AdminUserPublic]
    counts: UserCounts


class StatusChange(BaseModel):
    """Открыть или закрыть доступ.

    Вернуть заявку в состояние «ждёт решения» нельзя: решение уже принято,
    и делать вид, что его не было, — врать журналу.
    """

    status: UserStatus


class UserCreate(BaseModel):
    """Учётная запись, заводимая администратором.

    Пароль не принимается: он генерируется и показывается один раз.
    Придуманные вручную пароли повторяются от записи к записи.
    """

    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)

    # Либо новое рабочее пространство по названию, либо существующее по
    # идентификатору — второе нужно, чтобы добавить коллегу к уже
    # работающей команде.
    organization_name: str | None = Field(default=None, min_length=2, max_length=200)
    organization_id: uuid.UUID | None = None

    role: Role = Role.OWNER


class UserCreated(BaseModel):
    """Ответ на заведение учётной записи.

    Пароль здесь единственный раз за всю его жизнь: в базе лежит только
    хеш, и показать его снова будет неоткуда.
    """

    user: AdminUserPublic
    password: str
    organization_id: uuid.UUID
    organization_name: str
