"""Реестр ошибок: замечание, лента его событий, вложения.

Главный принцип процесса: найденная проблема не исправляется в момент обнаружения.
Сначала она получает постоянный код и попадает сюда, и только подтверждённая становится
основанием для новой редакции. Поэтому замечание неизменяемо в том, что было найдено, и
изменчиво только в том, что с ним решили.

Что найдено — код, снимки, описание, предложение, ссылки на блок, объект и редакцию —
охраняет триггер базы: «как было на момент обнаружения» не должно зависеть от аккуратности
кода. Что решили — статус, серьёзность, назначение — меняется, и каждое такое изменение
лежит событием в ленте. События не меняются и не удаляются вовсе.

Запись нельзя удалить и прямым запросом: удаление уходит только каскадом вместе с
организацией. Внешние ключи на книгу, главу, блок, объект и редакцию отложены до фиксации
и не имеют действия при удалении: проект с замечаниями не удалится сам собой, а каскад
организации, который убирает обе стороны, дойдёт до конца. Немедленная проверка здесь
упала бы посреди каскада.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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


class IssueCategory(str, enum.Enum):
    """О чём замечание. Набор закрыт: по нему считается статистика и фильтруется реестр."""

    TRANSLATION = "translation"
    TERMINOLOGY = "terminology"
    SEMANTIC = "semantic"
    NUMBER = "number"
    FORMULA = "formula"
    TABLE = "table"
    FIGURE = "figure"
    CODE = "code"
    TECHNICAL = "technical"
    STYLE = "style"
    CROSS_REFERENCE = "cross_reference"
    SOURCE_ERROR = "source_error"
    LAYOUT = "layout"


class IssueSeverity(str, enum.Enum):
    """Насколько плохо, если это уйдёт читателю. Критерии — в docs/DECISIONS.md.

    Порядок значений важен: в базе перечисление сортируется по нему, и «сначала критичные»
    — обычный `ORDER BY`.
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class IssueStatus(str, enum.Enum):
    """Где замечание в своём жизненном цикле. Переходы — в `services/issue_status.py`."""

    NEW = "new"
    NEEDS_CLARIFICATION = "needs_clarification"
    CONFIRMED = "confirmed"
    FIXED = "fixed"
    VERIFIED = "verified"
    CLOSED = "closed"
    REJECTED = "rejected"
    REOPENED = "reopened"


class IssueEventKind(str, enum.Enum):
    """Что произошло. Смена статуса — лишь одно из событий ленты."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    RECLASSIFIED = "reclassified"
    ASSIGNED = "assigned"
    COMMENTED = "commented"
    ATTACHED = "attached"
    ARCHIVED = "archived"
    RESTORED = "restored"


class Issue(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    __tablename__ = "issues"
    __table_args__ = (
        # Нумерация сквозная в главе, а код уникален в пространстве: его копируют в переписку,
        # и он обязан указывать на одну запись.
        UniqueConstraint("chapter_id", "number", name="issue_number"),
        UniqueConstraint("organization_id", "code", name="issue_code"),
        # Замечание ни к чему не привязанное — это заметка, а не запись реестра.
        CheckConstraint("block_id IS NOT NULL OR object_id IS NOT NULL", name="issue_has_subject"),
        # Исправлено без редакции — утверждение, которое нечем проверить.
        CheckConstraint(
            "status NOT IN ('FIXED', 'VERIFIED', 'CLOSED') OR fix_revision_id IS NOT NULL",
            name="issue_fix_has_revision",
        ),
        # В архив — только то, по чему решение принято: иначе незакрытое исчезнет из виду.
        CheckConstraint(
            "archived_at IS NULL OR status IN ('CLOSED', 'REJECTED')",
            name="issue_archive_only_decided",
        ),
        Index("issues_book_status", "book_id", "status"),
        Index("issues_chapter_status", "chapter_id", "status"),
        Index("issues_priority", "organization_id", "priority_score"),
        Index("issues_block", "block_id"),
        Index("issues_object", "object_id"),
        Index("issues_parent", "parent_issue_id"),
        # Повторный прогон проверки не должен рождать второй код той же находки.
        Index(
            "issues_dedupe",
            "organization_id",
            "dedupe_key",
            unique=True,
            postgresql_where="dedupe_key IS NOT NULL",
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", deferrable=True, initially="DEFERRED"),
        nullable=False,
    )
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("blocks.id", deferrable=True, initially="DEFERRED"),
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_objects.id", deferrable=True, initially="DEFERRED"),
    )
    # Замечание, из которого выросло это: регрессия после исправления. Родитель не закроется,
    # пока дочернее открыто.
    parent_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("issues.id", deferrable=True, initially="DEFERRED"),
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)

    category: Mapped[IssueCategory] = mapped_column(
        Enum(IssueCategory, name="issue_category", native_enum=True), nullable=False
    )
    severity: Mapped[IssueSeverity] = mapped_column(
        Enum(IssueSeverity, name="issue_severity", native_enum=True), nullable=False
    )
    status: Mapped[IssueStatus] = mapped_column(
        Enum(IssueStatus, name="issue_status", native_enum=True),
        nullable=False,
        default=IssueStatus.NEW,
    )

    # Вес для сортировки реестра, а не состояние: ничего из процесса от него не зависит.
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # Сколько блоков книги с тем же исходным текстом: повторится ли ошибка в других местах.
    impact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Нашла проверка, а не человек. Отдельным полем: пустой автор значит ещё и «учётную запись
    # удалили», и по нему одному их не различить.
    automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Как было на момент обнаружения. Текст дублируется намеренно: это показания, и они не
    # должны зависеть ни от дальнейшей судьбы блока, ни от чтения через три таблицы.
    source_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    target_snapshot: Mapped[str | None] = mapped_column(Text)
    discovered_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", deferrable=True, initially="DEFERRED"),
    )
    # Какие редакции были текущими у объекта в целом. Исправлением считается только другая.
    discovered_revisions: Mapped[list[str]] = mapped_column(
        postgresql.JSONB, nullable=False, default=list
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_fix: Mapped[str | None] = mapped_column(Text)
    # Отпечаток находки автоматической проверки. У человека его нет: два человека вправе
    # зарегистрировать одно и то же, и это решает проверяющий.
    dedupe_key: Mapped[str | None] = mapped_column(String(64))

    # Кто принял решение по находке: подтвердил или отклонил.
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Чем исправлено и кем. При повторном открытии очищаются: история остаётся в ленте.
    fix_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", deferrable=True, initially="DEFERRED"),
    )
    fixed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    fix_checked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueEvent(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Одна запись ленты. Неизменяема: лента и есть ответ на вопрос «кто и почему»."""

    __tablename__ = "issue_events"
    __table_args__ = (Index("issue_events_issue", "issue_id", "created_at"),)

    issue_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[IssueEventKind] = mapped_column(
        Enum(IssueEventKind, name="issue_event_kind", native_enum=True), nullable=False
    )
    from_status: Mapped[IssueStatus | None] = mapped_column(
        Enum(IssueStatus, name="issue_status", native_enum=True)
    )
    to_status: Mapped[IssueStatus | None] = mapped_column(
        Enum(IssueStatus, name="issue_status", native_enum=True)
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    related_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("translation_revisions.id", deferrable=True, initially="DEFERRED"),
    )
    # Что именно изменилось, когда это не статус: прежняя и новая серьёзность, назначение.
    payload: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False, default=dict)


class IssueAttachment(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Снимок страницы или формулы к замечанию.

    Тип определяется по байтам при приёме, а не по имени и не со слов браузера.
    """

    __tablename__ = "issue_attachments"
    __table_args__ = (Index("issue_attachments_issue", "issue_id"),)

    issue_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(60), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
