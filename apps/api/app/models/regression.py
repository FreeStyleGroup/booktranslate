"""Регрессия после исправления: что могло задеть изменение и что с этим решили.

Правка не расходится по книге сама. Сервис вычисляет, какие места связаны с исправленным, и
заводит прогон: по каждому обязательному месту должно быть решение. Закрыть замечание нельзя, пока
прогон не завершён, потому что исправление, сломавшее соседнюю ссылку, исправлением не считается.

Прогон относится к конкретной редакции: другое исправление — другой текст и другой прогон.
"""

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class DependencyKind(str, enum.Enum):
    SAME_SOURCE_REPEAT = "same_source_repeat"  # тот же исходный текст в книге
    TERM_USAGE = "term_usage"  # изменилось употребление термина
    OBJECT_REFERENCE = "object_reference"  # упоминания того же объекта
    CROSS_REFERENCE = "cross_reference"  # ссылки на этот раздел по номеру
    ADJACENT_CONTEXT = "adjacent_context"  # соседние блоки
    TABLE_CAPTION = "table_caption"  # подпись таблицы, в которой стоит блок
    FIGURE_CAPTION = "figure_caption"  # рисунок, подпись которого правили


class RegressionStatus(str, enum.Enum):
    OPEN = "open"
    COMPLETED = "completed"
    # Замечание открыли заново: прогон был про другое исправление.
    SUPERSEDED = "superseded"


class RegressionDecision(str, enum.Enum):
    PENDING = "pending"
    NOT_AFFECTED = "not_affected"  # посмотрели: связь есть, а исправлять нечего
    PROPAGATED = "propagated"  # то же исправление применено сюда новой редакцией
    ISSUE_CREATED = "issue_created"  # здесь своя проблема: заведено дочернее замечание


class RegressionRun(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "regression_runs"
    __table_args__ = (
        UniqueConstraint("issue_id", "fix_revision_id", name="regression_run_once"),
        Index("regression_runs_issue", "issue_id", "created_at"),
    )

    issue_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    fix_revision_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[RegressionStatus] = mapped_column(
        Enum(RegressionStatus, name="regression_status", native_enum=True),
        nullable=False,
        default=RegressionStatus.OPEN,
    )


class RegressionItem(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Одно затронутое место и решение по нему."""

    __tablename__ = "regression_items"
    __table_args__ = (
        CheckConstraint(
            "block_id IS NOT NULL OR object_id IS NOT NULL", name="regression_item_has_subject"
        ),
        Index("regression_items_run", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("regression_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[DependencyKind] = mapped_column(
        Enum(DependencyKind, name="dependency_kind", native_enum=True), nullable=False
    )
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE")
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("book_objects.id", ondelete="CASCADE")
    )
    # Обязательное держит закрытие замечания. Соседние блоки только показываются.
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Текущая редакция места на момент расчёта: решение относится к этому тексту.
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="CASCADE"),
    )
    # Что предлагается поставить сюда: только у повтора исходного текста.
    proposed_text: Mapped[str | None] = mapped_column(Text)
    # Текст места совпадал с исправленным дословно: применять безопасно.
    safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    decision: Mapped[RegressionDecision] = mapped_column(
        Enum(RegressionDecision, name="regression_decision", native_enum=True),
        nullable=False,
        default=RegressionDecision.PENDING,
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    applied_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", deferrable=True, initially="DEFERRED"),
    )
    child_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("issues.id", deferrable=True, initially="DEFERRED"),
    )
