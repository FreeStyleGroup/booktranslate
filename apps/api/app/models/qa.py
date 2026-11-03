"""Прогоны проверок, находки и покрытие редакций.

Прогон проверяет не «главу», а определённый набор редакций: его сумма записана. Покрытие лежит на
редакции, а не на блоке: новая редакция — это новый текст, и отметка старой к ней не относится.

Находка всегда чем-то кончается. Либо за ней стоит замечание реестра, либо записано правило, по
которому регистрировать незачем: так гарантирует ограничение базы, и находки, про которую
забыли, быть не может.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
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
from app.models.issue import IssueCategory, IssueSeverity
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class QAKind(str, enum.Enum):
    # Правила: быстро, бесплатно, повторяемо. Отметка «формально проверено».
    DETERMINISTIC = "deterministic"
    # Модель сравнивает смысл: стоит денег. Отметка «смысловая сверка выполнена».
    SEMANTIC = "semantic"


class QAScope(str, enum.Enum):
    """Что отдавать на смысловую сверку. Второй проход модели по всей книге удваивает расход."""

    # Числа, формулы и код внутри текста, таблицы, предупреждения, обязательные термины.
    RISKY = "risky"
    ALL = "all"


class FindingDisposition(str, enum.Enum):
    REGISTERED = "registered"
    NOT_REQUIRED = "not_required"


class QARun(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Один прогон проверки главы. Состояние — в его задании, как и у прогона перевода."""

    __tablename__ = "qa_runs"
    __table_args__ = (Index("qa_runs_chapter", "chapter_id", "created_at"),)

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    master_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapter_masters.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[QAKind] = mapped_column(
        Enum(QAKind, name="qa_kind", native_enum=True), nullable=False
    )
    scope: Mapped[QAScope] = mapped_column(
        Enum(QAScope, name="qa_scope", native_enum=True), nullable=False, default=QAScope.ALL
    )
    # Какими правилами или каким промптом проверено.
    check_profile_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # Какой текст проверялся: сумма набора «блок → редакция» на момент запуска.
    revision_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    blocks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocks_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Без перевода проверять нечего: они не проверены, и об этом надо сказать.
    blocks_untranslated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issues_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Докуда дошли. Повторный заход продолжает, а не платит второй раз.
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    # Блоки, которые модель проверить отказалась: без отметки и с причиной.
    rejections: Mapped[list[dict[str, Any]]] = mapped_column(
        postgresql.JSONB, nullable=False, default=list
    )

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RevisionCheck(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Отметка: эта редакция проверена таким видом проверки и такой версией правил."""

    __tablename__ = "revision_checks"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "kind", "check_profile_version", name="revision_check_once"
        ),
        Index("revision_checks_revision", "revision_id"),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    qa_run_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[QAKind] = mapped_column(
        Enum(QAKind, name="qa_kind", native_enum=True), nullable=False
    )
    check_profile_version: Mapped[str] = mapped_column(String(40), nullable=False)


class QAFinding(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "qa_findings"
    __table_args__ = (
        Index("qa_findings_run", "qa_run_id"),
        Index("qa_findings_chapter", "chapter_id", "check_name"),
        # Находка либо связана с замечанием, либо признана ненужной по названному правилу.
        CheckConstraint(
            "(disposition = 'REGISTERED' AND issue_id IS NOT NULL AND rule IS NULL) "
            "OR (disposition = 'NOT_REQUIRED' AND issue_id IS NULL AND rule IS NOT NULL)",
            name="qa_finding_is_resolved",
        ),
    )

    qa_run_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    block_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[QAKind] = mapped_column(
        Enum(QAKind, name="qa_kind", native_enum=True), nullable=False
    )
    check_name: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[IssueCategory] = mapped_column(
        Enum(IssueCategory, name="issue_category", native_enum=True), nullable=False
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, name="issue_severity", native_enum=True), nullable=False
    )

    disposition: Mapped[FindingDisposition] = mapped_column(
        Enum(FindingDisposition, name="qa_finding_disposition", native_enum=True), nullable=False
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("issues.id", deferrable=True, initially="DEFERRED"),
    )
    rule: Mapped[str | None] = mapped_column(String(40))
