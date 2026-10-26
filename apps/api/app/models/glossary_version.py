"""Версии глоссария: что именно было утверждено как терминология книги.

Рабочий словарь живой — его правят, загружают, чистят от дубликатов. По
нему нельзя ответить на вопрос «с каким глоссарием переводилась глава 3»:
через месяц он уже другой. Поэтому перевод опирается не на словарь, а на
его утверждённую версию — неизменяемый снимок с номером, контрольной
суммой, автором и временем утверждения.

Версия относится к книге целиком либо к одной главе. Книжная — решение о
единообразии: утверждая её, отменяют главные версии этой книги, иначе в
главах снова разъедутся названия. Главная нужна, чтобы начать работу с
готовой главы, не дожидаясь всей книги; она действует для своей главы,
пока не утвердят следующую книжную.

Рядом со снимком хранится, чем он отличается от предыдущей утверждённой
версии и какие блоки книги эти отличия задевают: смена обязательного
термина — не правка словаря, а событие, после которого надо знать, что
перепроверять.
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
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTermStatus
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class GlossaryVersionStatus(str, enum.Enum):
    DRAFT = "draft"  # собрана, ждёт утверждения
    APPROVED = "approved"  # утверждена — по ней переводят
    SUPERSEDED = "superseded"  # заменена следующей и в работу больше не идёт


class GlossaryScope(str, enum.Enum):
    BOOK = "book"
    CHAPTER = "chapter"


class TermChangeKind(str, enum.Enum):
    """Чем обязательный термин версии отличается от предыдущей."""

    ADDED = "added"  # появился
    CHANGED = "changed"  # перевод, варианты или правило стали другими
    REMOVED = "removed"  # снят или перестал быть обязательным


class GlossaryVersion(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Снимок терминологии книги или главы с номером и решением по нему.

    Номер сквозной по книге (`v3`), какой бы ни была область: людям
    проще говорить «глоссарий v3», чем «третья книжная или вторая главная».

    Черновик и утверждённая версия — по одной на область: два черновика
    одной главы — это два ответа на один вопрос, и какой из них утверждать,
    было бы непонятно. Это держит база: два частичных уникальных индекса,
    где пустая глава (книжная версия) равна пустой.
    """

    __tablename__ = "glossary_versions"
    __table_args__ = (
        UniqueConstraint("book_id", "number", name="glossary_version_number"),
        Index(
            "glossary_version_one_draft",
            "book_id",
            "chapter_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "glossary_version_one_approved",
            "book_id",
            "chapter_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_editions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Пусто — версия книги целиком. Область не хранится отдельной колонкой:
    # она однозначно следует из главы, и вторая запись того же значения
    # однажды разошлась бы с первой.
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        index=True,
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GlossaryVersionStatus] = mapped_column(
        Enum(GlossaryVersionStatus, name="glossary_version_status", native_enum=True),
        nullable=False,
        default=GlossaryVersionStatus.DRAFT,
    )

    # С какой утверждённой версией сравнивался снимок. Пусто у первой:
    # сравнивать не с чем, и переводить по прежнему глоссарию никто не мог.
    base_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("glossary_versions.id", ondelete="SET NULL")
    )
    # Какая версия эту заменила.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("glossary_versions.id", ondelete="SET NULL")
    )

    # SHA-256 канонической записи терминов снимка: по ней сверяют, что
    # версия, на которую ссылается перевод, — та самая.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    # Число терминов снимка. Хранится, хотя считается: снимок неизменяем, и
    # разойтись числу не с чем, а список версий без него — запрос на группу.
    term_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Главы, которые покрывает снимок, и версия мастера каждой на момент
    # сборки: `[{"chapter_id": …, "master_id": …}]`. Терминология решается
    # по тексту, и решение о тексте прежней версии мастера о новой ничего
    # не говорит.
    basis: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)

    # Основание утверждения пустой версии — решение «терминов нет». Пустой
    # глоссарий без него — не решение, а пропущенный этап.
    empty_reason: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def scope(self) -> GlossaryScope:
        return GlossaryScope.BOOK if self.chapter_id is None else GlossaryScope.CHAPTER

    @property
    def label(self) -> str:
        return f"v{self.number}"


class GlossaryVersionTerm(UUIDPrimaryKey, TenantMixin, Base):
    """Термин в снимке — копия решения на момент сборки версии.

    Копия, а не ссылка на запись словаря: запись могут поправить или
    удалить, а версия обязана остаться такой, какой её утвердили. Ссылка
    на исходную запись хранится рядом — чтобы из версии перейти к живому
    термину, — и гасится при его удалении.

    Без отметок времени: строка снимка не меняется, её время — время
    версии.
    """

    __tablename__ = "glossary_version_terms"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "source_term_normalized", name="glossary_version_term_source"
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("glossary_terms.id", ondelete="SET NULL")
    )

    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    source_term_normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    target_term: Mapped[str] = mapped_column(String(300), nullable=False)
    allowed_variants: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String(300)), nullable=False
    )
    kind: Mapped[GlossaryEntryKind] = mapped_column(
        Enum(GlossaryEntryKind, name="glossary_entry_kind", native_enum=True), nullable=False
    )
    status: Mapped[GlossaryTermStatus] = mapped_column(
        Enum(GlossaryTermStatus, name="glossary_term_status", native_enum=True), nullable=False
    )
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    first_use_rule: Mapped[FirstUseRule] = mapped_column(
        Enum(FirstUseRule, name="first_use_rule", native_enum=True), nullable=False
    )
    domain: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)


class GlossaryVersionChange(UUIDPrimaryKey, TenantMixin, Base):
    """Отличие обязательного термина версии от предыдущей утверждённой.

    Только обязательные: необязательный термин — подсказка модели, и
    перевод из-за его смены не становится неверным. Прежнее и новое
    решение — копиями, как в снимке: по ним видно, что именно сменилось.
    """

    __tablename__ = "glossary_version_changes"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "source_term_normalized", name="glossary_version_change_source"
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    source_term_normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[TermChangeKind] = mapped_column(
        Enum(TermChangeKind, name="term_change_kind", native_enum=True), nullable=False
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(postgresql.JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(postgresql.JSONB)


class GlossaryVersionImpact(UUIDPrimaryKey, TenantMixin, Base):
    """Блок, который задевает изменение термина: в его тексте этот термин есть.

    Список собирается вместе со снимком, по тем версиям мастера, что
    перечислены в его основании, и дальше не меняется — это ответ на
    вопрос «что надо было перепроверить после этой версии глоссария».
    """

    __tablename__ = "glossary_version_impacts"
    __table_args__ = (
        UniqueConstraint("change_id", "block_id", name="glossary_version_impact_block"),
    )

    change_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("glossary_version_changes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
