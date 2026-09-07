"""Организация, пользователи и участие.

Организация — корень мультитенантности: всё остальное принадлежит ей.
Пользователь живёт отдельно от организации, потому что один человек может
работать сразу в нескольких (штатный переводчик и подрядчик — обычное дело),
а связь «кто где и с какой ролью» вынесена в участие.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
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


class UserStatus(str, enum.Enum):
    """Состояние доступа учётной записи.

    Три состояния, а не флаг «включён»: «ещё не рассмотрели» и «закрыли
    доступ» — разные вещи и для человека, и для того, кто разбирает список.
    Флагом их не различить, а по нему потом невозможно ответить на вопрос
    «эту заявку отклонили или до неё просто не дошли руки».
    """

    PENDING = "pending"  # заявка подана, ждёт решения администратора
    ACTIVE = "active"  # доступ открыт
    SUSPENDED = "suspended"  # доступ закрыт: отклонён или приостановлен


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

    # Доступ открывает администратор. Умолчание — «ждёт решения»: регистрация
    # это заявка, а не пропуск, и сама по себе она никого внутрь не пускает.
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", native_enum=True),
        nullable=False,
        default=UserStatus.PENDING,
        index=True,
    )

    # Администратор площадки — не роль в организации. Роль говорит, что
    # человек может в своём рабочем пространстве; это — что он распоряжается
    # доступом на всей площадке, и смешивать их нельзя.
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Кто и когда менял состояние доступа. Без этого список пользователей
    # отвечает на «кто закрыт», но не на «кто закрыл и когда» — а спрашивают
    # обычно второе.
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        # SET NULL: уход администратора не должен стирать след того, что
        # решение принималось.
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    # Последний вход. Отвечает на «пользуется ли человек доступом» — вопрос,
    # который возникает при первой же чистке списка.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
