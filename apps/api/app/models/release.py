"""Выпуски: финальная версия главы и сборка книги.

Рабочий текст живёт и меняется, выпуск нет. Финальная версия главы — это манифест: какие именно
редакции каких блоков и какие объекты в неё вошли, с контрольной суммой. После утверждения запись
неизменяема, и это держит база, а не только сервис: исправление даёт новую версию. Поэтому правка
рабочего текста не может задеть уже утверждённый выпуск, а по манифесту восстанавливается каждая
редакция.

Сборка книги называет версии глав явно. «Последняя» допустима только при выборе, в самой записи её
нет: иначе один и тот же выпуск менял бы состав сам по себе."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class ReleaseStatus(str, enum.Enum):
    DRAFT = "draft"  # собрана, но ещё никем не утверждена: в книгу не идёт
    APPROVED = "approved"  # утверждена: источник для книги, больше не меняется


class BookReleaseStatus(str, enum.Enum):
    BUILT = "built"  # состав закреплён, идёт контроль выпуска
    PASSED = "passed"  # контроль пройден: больше не меняется


def _deferred(target: str) -> ForeignKey:
    """Ссылка, проверяемая в конце транзакции: так её не роняет каскад удаления организации."""
    return ForeignKey(target, deferrable=True, initially="DEFERRED")


class ChapterRelease(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Финальная версия главы: `BK01-CH03-FINAL-v1.0`."""

    __tablename__ = "chapter_releases"
    __table_args__ = (
        UniqueConstraint(
            "chapter_id", "version_major", "version_minor", name="chapter_release_version"
        ),
        # Черновик на главу один: два разошлись бы, и утверждение одного обесценивало бы другой.
        Index(
            "chapter_release_one_draft",
            "chapter_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        Index("chapter_releases_book", "book_id"),
        CheckConstraint(
            "status <> 'APPROVED' OR (approved_at IS NOT NULL)", name="chapter_release_approved"
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("book_editions.id"), nullable=False
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("chapters.id"), nullable=False
    )
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[ReleaseStatus] = mapped_column(
        Enum(ReleaseStatus, name="release_status", native_enum=True),
        nullable=False,
        default=ReleaseStatus.DRAFT,
    )
    # Какие редакции и объекты вошли. Канонический вид и его сумма: см. `canonical.canonical_json`.
    manifest: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    master_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("chapter_masters.id"), nullable=False
    )
    glossary_version_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("glossary_versions.id")
    )
    # На какие работы опирается версия: по ним видно, кто и когда это смотрел.
    technical_review_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("review_runs.id"), nullable=False
    )
    literary_review_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("review_runs.id"), nullable=False
    )
    final_compare_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("review_runs.id"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookRelease(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Выпуск книги: `BK01-RELEASE-v1.0`. Манифест перечисляет версии глав и порядок."""

    __tablename__ = "book_releases"
    __table_args__ = (
        UniqueConstraint("book_id", "version_major", "version_minor", name="book_release_version"),
        UniqueConstraint("book_id", "manifest_hash", name="book_release_manifest"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("book_editions.id"), nullable=False
    )
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[BookReleaseStatus] = mapped_column(
        Enum(BookReleaseStatus, name="book_release_status", native_enum=True),
        nullable=False,
        default=BookReleaseStatus.BUILT,
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class BookReleaseChapter(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Глава в выпуске. Отдельной строкой: база не даст удалить версию главы из-под выпуска."""

    __tablename__ = "book_release_chapters"
    __table_args__ = (
        UniqueConstraint("release_id", "position", name="book_release_chapter_position"),
        UniqueConstraint("release_id", "chapter_release_id", name="book_release_chapter_once"),
    )

    release_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_releases.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_release_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("chapter_releases.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ArtifactFormat(str, enum.Enum):
    DOCX = "docx"
    PDF = "pdf"


class PageStatus(str, enum.Enum):
    UNREVIEWED = "unreviewed"
    PASS = "pass"
    ISSUE = "issue"
    STALE = "stale"  # файл пересобран: этот аудит был про другой файл


class ExportArtifact(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Файл выпуска. Новая сборка заводит новый файл, прежний остаётся устаревшим."""

    __tablename__ = "export_artifacts"
    __table_args__ = (
        Index(
            "export_artifact_current",
            "release_id",
            "format",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    release_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_releases.id", ondelete="CASCADE"),
        nullable=False,
    )
    format: Mapped[ArtifactFormat] = mapped_column(
        Enum(ArtifactFormat, name="artifact_format", native_enum=True), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    # На каждую страницу: какие блоки на ней стоят. По этому страница находит своё замечание.
    page_map: Mapped[list[list[str]] | None] = mapped_column(postgresql.JSONB)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PageAudit(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Результат просмотра одной страницы конкретного файла PDF."""

    __tablename__ = "page_audits"
    __table_args__ = (UniqueConstraint("artifact_id", "page_no", name="page_audit_once"),)

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("export_artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PageStatus] = mapped_column(
        Enum(PageStatus, name="page_status", native_enum=True),
        nullable=False,
        default=PageStatus.UNREVIEWED,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), _deferred("issues.id")
    )


class ReleasePass(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """PASS как событие: кто, когда, снимок проверки и суммы файлов. Запись неизменяема."""

    __tablename__ = "release_passes"

    release_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("book_releases.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_snapshot: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(postgresql.JSONB, nullable=False)
