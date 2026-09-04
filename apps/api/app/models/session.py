"""Сессия обновления доступа.

Refresh-токен хранится записью, а не самодостаточной подписью: только так
его можно отозвать — при выходе, смене пароля или подозрении на кражу.
В базе лежит хеш, а не сам токен.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKey


class RefreshSession(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "refresh_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Уникальность нужна не для скорости, а как страховка: два токена с
    # одним хешем означали бы, что генератор случайности сломан.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Куда выдан новый токен при ротации. Если придут по уже
    # использованному токену, по цепочке видно, что сессию украли, и
    # гасить надо всю ветку, а не одну запись.
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("refresh_sessions.id", ondelete="SET NULL"),
    )

    # Чем и откуда вошли. Показывается пользователю в списке сессий —
    # иначе кнопка «выйти на всех устройствах» ничего ему не говорит.
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(45))
