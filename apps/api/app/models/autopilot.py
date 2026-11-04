"""Автоматический режим: прогон конвейера для всей книги.

Это не отдельный путь через сервис. Книга проходит тот же конвейер, с теми же кодами, манифестом и
гейтами, только решения по условиям принимает сервис. Каждое такое решение пишется в журнал и
помечается как автоматическое. Если решить уверенно нельзя, прогон останавливается и говорит, что
именно ждёт человека.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class AutopilotStatus(str, enum.Enum):
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"  # нужно решение: что именно, сказано в `waiting`
    DONE = "done"
    CANCELLED = "cancelled"


class AutopilotRun(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "autopilot_runs"
    __table_args__ = (
        # Один живой прогон на книгу: два принимали бы решения наперегонки.
        Index(
            "autopilot_runs_live_book",
            "book_id",
            unique=True,
            postgresql_where=text("status IN ('RUNNING', 'WAITING_HUMAN')"),
        ),
        Index("autopilot_runs_queue", "status", "lease_until"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[AutopilotStatus] = mapped_column(
        Enum(AutopilotStatus, name="autopilot_status", native_enum=True),
        nullable=False,
        default=AutopilotStatus.RUNNING,
    )
    # На каком шаге конвейера книга сейчас.
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    # Пороги, по которым сервис решает сам: часть решения, поэтому хранятся с прогоном.
    profile: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    # Что ждёт человека: коды и фразы, со ссылками на замечание или главу.
    waiting: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)
    # Сколько раз пробовали один и тот же шаг: сервис не должен платить за повтор без конца.
    attempts: Mapped[dict[str, int]] = mapped_column(postgresql.JSONB, nullable=False)
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("book_releases.id", ondelete="SET NULL")
    )
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Сервис приходит к прогону короткими заходами. Срок не даёт двум рабочим взять его сразу, а
    # упавшему рабочему — держать его вечно.
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Расход на перевод кандидатов в термины: у остальных работ он записан в их прогонах.
    model: Mapped[str | None] = mapped_column(String(120))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
