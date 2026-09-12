"""Приглашение в рабочее пространство.

Доступ в пространство открывает его владелец, а не администратор площадки:
площадка одобряет заказчика, а кого заказчик пускает к своим книгам —
его дело. Поэтому приглашённый по ссылке человек получает действующую
учётную запись сразу, без второго одобрения.

Приглашение — на почту, и в базе лежит хеш ссылки, а не сама ссылка:
утёкшая копия таблицы не должна давать вход. Само значение уходит письмом
и показывается пригласившему один раз — как выданный пароль.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey
from app.models.organization import Organization, Role, User


class Invitation(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        # На одну почту — одно открытое приглашение в пространство: второе
        # означало бы две ссылки с разными ролями, и какая сработает,
        # решал бы порядок нажатий.
        Index(
            "invitations_open_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL"),
        ),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="membership_role", native_enum=True), nullable=False
    )

    # SHA-256 ссылки. Сама ссылка не хранится: см. заголовок модуля.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # SET NULL: уход пригласившего не должен стирать след того, что
    # приглашение выписывалось.
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Принятое приглашение остаётся: по нему видно, кто кого позвал и
    # когда человек пришёл. Отозванное — удаляется: отзыв означает «этого
    # приглашения не было».
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    organization: Mapped[Organization] = relationship()
    invited_by: Mapped[User | None] = relationship(foreign_keys=[invited_by_id])
