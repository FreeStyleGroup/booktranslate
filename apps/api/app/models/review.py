"""Прогоны редактуры и сверки: кто что посмотрел и на каком именно тексте.

Техническая редактура, литературная редактура и финальная сверка — один и тот же объект с разным
видом: у них одинаковый состав и одинаковое покрытие. Покрытие называет редакцию, поэтому новая
редакция возвращает блок в очередь сама: отметка о старом тексте просто перестаёт совпадать с
текущим. Снимать её некому и незачем.

Отметка ставится только человеком и только по одному месту. Массовой кнопки нет намеренно: отметка
«сверено» ничего не стоит, если её можно поставить не глядя.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class ReviewKind(str, enum.Enum):
    TECHNICAL = "technical"
    LITERARY = "literary"
    FINAL_COMPARE = "final_compare"


class ReviewStatus(str, enum.Enum):
    OPEN = "open"
    COMPLETED = "completed"


class ReviewResult(str, enum.Enum):
    OK = "ok"  # посмотрели, всё верно
    ISSUE = "issue"  # посмотрели и завели замечание


class EditReason(str, enum.Enum):
    """Зачем правили стиль: по этому видно, что смысл не должен был измениться."""

    STYLE = "style"
    CALQUE = "calque"
    READABILITY = "readability"


class ReviewRun(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "review_runs"
    __table_args__ = (
        # Одна открытая работа каждого вида на главу: две разошлись бы в покрытии.
        Index(
            "review_runs_open",
            "chapter_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
        Index("review_runs_chapter", "chapter_id", "kind", "created_at"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ReviewKind] = mapped_column(
        Enum(ReviewKind, name="review_kind", native_enum=True), nullable=False
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", native_enum=True),
        nullable=False,
        default=ReviewStatus.OPEN,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # С какого текста начали и на каком закончили: сумма набора «блок → редакция».
    base_revision_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_revision_set_hash: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewCoverage(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Отметка: это место посмотрели именно в этом виде."""

    __tablename__ = "review_coverage"
    __table_args__ = (
        CheckConstraint(
            "(block_id IS NOT NULL AND revision_id IS NOT NULL AND object_id IS NULL "
            "AND content_hash IS NULL) "
            "OR (object_id IS NOT NULL AND content_hash IS NOT NULL AND block_id IS NULL "
            "AND revision_id IS NULL)",
            name="review_coverage_subject",
        ),
        Index("review_coverage_run", "run_id"),
        Index(
            "review_coverage_block_once",
            "run_id",
            "block_id",
            "revision_id",
            unique=True,
            postgresql_where=text("block_id IS NOT NULL"),
        ),
        Index(
            "review_coverage_object_once",
            "run_id",
            "object_id",
            "content_hash",
            unique=True,
            postgresql_where=text("object_id IS NOT NULL"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE")
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="CASCADE"),
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("book_objects.id", ondelete="CASCADE")
    )
    # Сумма объекта и текущих редакций его блоков: изменилось что угодно — отметка не действует.
    content_hash: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[ReviewResult] = mapped_column(
        Enum(ReviewResult, name="review_result", native_enum=True), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
