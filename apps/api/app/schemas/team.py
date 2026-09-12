"""Схемы команды и приглашений."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.organization import Role


class MemberPublic(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    # По последнему входу видно, пользуется ли человек доступом, — первый
    # вопрос при чистке команды.
    last_login_at: datetime | None
    joined_at: datetime


class InvitationPublic(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    invited_by: str | None
    created_at: datetime
    expires_at: datetime
    # Просроченное приглашение остаётся в списке: его надо видеть, чтобы
    # отозвать или выписать заново, а не гадать, почему человек не пришёл.
    expired: bool


class TeamPublic(BaseModel):
    members: list[MemberPublic]
    invitations: list[InvitationPublic]
    # Роль смотрящего: по ней витрина решает, показывать ли управление.
    # Отдельным полем, а не поиском себя в списке: список может быть
    # отобран, а роль нужна всегда.
    my_role: Role


class InviteRequest(BaseModel):
    email: EmailStr
    role: Role = Role.TRANSLATOR


class InvitedPublic(BaseModel):
    invitation: InvitationPublic
    # Ссылка показывается один раз: если письмо не ушло, её передают
    # сами. В базе только хеш.
    link: str
    email_sent: bool
    email_detail: str


class RoleChange(BaseModel):
    role: Role


class InvitationLookup(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class InvitationPreview(BaseModel):
    """Что видит человек, открывший ссылку, до того как согласиться."""

    organization_name: str
    email: str
    role: Role
    invited_by: str | None
    expires_at: datetime
    # Есть ли уже учётная запись на эту почту: тогда нужен вход, а не
    # пароль в форме.
    has_account: bool


class InvitationAccept(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    # Для новой учётной записи. Та же нижняя граница, что при регистрации.
    password: str | None = Field(default=None, min_length=12, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)


class AcceptedPublic(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    email: str
    new_account: bool
