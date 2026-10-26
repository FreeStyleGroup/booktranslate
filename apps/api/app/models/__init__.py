"""Доменные модели.

Импорт здесь нужен не для удобства, а для Alembic: autogenerate видит только
те таблицы, чьи классы уже загружены к моменту сравнения со схемой базы.
Модель, забытая в этом списке, молча не попадёт в миграцию.
"""

from app.models.audit import AuditEvent
from app.models.block import Block, BlockKind, SegmentChunk
from app.models.book import BookEdition, BookStatus, SourceValidationResult
from app.models.book_object import BookObject, ObjectReference, ObjectType, ReferenceKind
from app.models.catalog import CatalogEntry
from app.models.chapter import BoundaryStatus, Chapter, ChapterOrigin
from app.models.coding import CodeCounter, CodeKind
from app.models.document import Document, DocumentStatus, SourceFormat, SourceRole
from app.models.job import JobState, TranslationJob
from app.models.master import ChapterMaster
from app.models.memory import (
    GlossaryEntryKind,
    GlossaryTerm,
    GlossaryTermStatus,
    GlossaryUpload,
    TranslationUnit,
)
from app.models.notification import NotificationSettings
from app.models.organization import Membership, Organization, Role, User, UserStatus
from app.models.project import Project
from app.models.segment import Segment, SegmentStatus
from app.models.session import RefreshSession
from app.models.shared import SharedTerm
from app.models.team import Invitation
from app.models.terminology import TermCandidate, TermCandidateStatus
from app.models.workspace import WorkspaceSettings

__all__ = [
    "AuditEvent",
    "Block",
    "BlockKind",
    "BookEdition",
    "BookObject",
    "BookStatus",
    "BoundaryStatus",
    "CatalogEntry",
    "Chapter",
    "ChapterMaster",
    "ChapterOrigin",
    "CodeCounter",
    "CodeKind",
    "Document",
    "DocumentStatus",
    "GlossaryEntryKind",
    "GlossaryTerm",
    "GlossaryTermStatus",
    "GlossaryUpload",
    "Invitation",
    "JobState",
    "Membership",
    "NotificationSettings",
    "ObjectReference",
    "ObjectType",
    "Organization",
    "Project",
    "ReferenceKind",
    "RefreshSession",
    "Role",
    "Segment",
    "SegmentChunk",
    "SegmentStatus",
    "SharedTerm",
    "SourceFormat",
    "SourceRole",
    "SourceValidationResult",
    "TermCandidate",
    "TermCandidateStatus",
    "TranslationJob",
    "TranslationUnit",
    "User",
    "UserStatus",
    "WorkspaceSettings",
]
