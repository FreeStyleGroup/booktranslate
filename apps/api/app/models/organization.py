"""Организация, пользователи и участие.

Организация — корень мультитенантности: всё остальное принадлежит ей.
Пользователь живёт отдельно от организации, потому что один человек может
работать сразу в нескольких (штатный переводчик и подрядчик — обычное дело),
а связь «кто где и с какой ролью» вынесена в участие.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKey


class Role(str, enum.Enum):
    """Роль участника в организации.

    Роль хранится на участии, а не на пользователе: в одной организации
    человек владелец, в другой — приглашённый редактор.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    TRANSLATOR = "translator"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Organization(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Короткое имя для адресов. Уникально глобально: по нему адресуются
    # рабочие пространства.
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    # Хеш, а не пароль. Колонка допускает пустоту: вход по внешнему провайдеру
    # или по приглашению обходится без пароля вовсе.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Membership(UUIDPrimaryKey, TimestampMixin, Base):
    """Участие пользователя в организации с ролью."""

    __tablename__ = "memberships"
    __table_args__ = (
        # Второе участие того же человека в той же организации означало бы
        # две разные роли одновременно — и непредсказуемые права.
        UniqueConstraint("organization_id", "user_id", name="organization_user"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="membership_role", native_enum=True), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
