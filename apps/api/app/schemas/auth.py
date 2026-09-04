"""Схемы входа и регистрации.

Схемы отделены от моделей базы намеренно: наружу уходит не то же самое,
что лежит в таблице. Хеш пароля, служебные поля и чужие идентификаторы в
ответ попадать не должны, а «забыли исключить» — самая обычная утечка.
"""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.organization import Role


class RegisterRequest(BaseModel):
    """Первый вход в систему: человек и его организация создаются вместе.

    Отдельной регистрации «пользователь без организации» нет: работать
    в одиночку в платформе не с чем — проекты, документы и права живут
    внутри организации.
    """

    email: EmailStr
    # Нижняя граница — рекомендация NIST: длина важнее символьной
    # экзотики, а верхняя защищает от мегабайтной строки на вход Argon2.
    password: str = Field(min_length=12, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Срок жизни токена доступа в секундах")


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None


class MembershipPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    organization_name: str
    role: Role


class CurrentUser(BaseModel):
    """Ответ «кто я»: сам пользователь и его организации с ролями.

    Витрине этого достаточно, чтобы нарисовать переключатель рабочих
    пространств и скрыть недоступные разделы, не делая второй запрос.
    """

    user: UserPublic
    memberships: list[MembershipPublic]
