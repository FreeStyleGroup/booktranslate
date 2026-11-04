"""Перевод надписей на рисунках.

Оригинал изображения не меняется никогда: перевод — отдельный файл со ссылкой на сумму оригинала.
Каждая правка заводит новую версию, поэтому видно, что предложила модель и что поправил человек.
Решение по картинке явное: перевод утверждён, оставлен оригинал или надписей нет. Без решения
глава в выпуск не идёт.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class FigureStatus(str, enum.Enum):
    DRAFT = "draft"  # ждёт решения человека
    APPROVED = "approved"  # перевод проверен рядом с оригиналом
    KEPT_ORIGINAL = "kept_original"  # решили оставить как в книге
    NO_TEXT = "no_text"  # надписей нет: переводить нечего


# Что считается решением. Черновик решением не считается.
DECIDED_STATUSES = (FigureStatus.APPROVED, FigureStatus.KEPT_ORIGINAL, FigureStatus.NO_TEXT)


class FigureTranslation(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "figure_translations"
    __table_args__ = (
        UniqueConstraint("object_id", "image_index", "version", name="figure_translation_version"),
        Index("figure_translations_chapter", "chapter_id"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_index: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Сумма оригинала: перевод относится именно к этой картинке.
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[FigureStatus] = mapped_column(
        Enum(FigureStatus, name="figure_status", native_enum=True), nullable=False
    )
    # Надписи: где стоят, что написано, чем заменить и откуда взят перевод.
    regions: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)
    # Сервис не уверен: без человека такой перевод не пройдёт и в автоматическом режиме.
    needs_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    # Чем читали и переводили: по этому полю считается расход.
    model: Mapped[str | None] = mapped_column(String(120))
    # Готовый файл с переводом. Пусто, если перерисовывать нечего.
    asset_key: Mapped[str | None] = mapped_column(String(500))
    asset_sha256: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
