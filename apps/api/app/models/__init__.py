"""Доменные модели.

Импорт здесь нужен не для удобства, а для Alembic: autogenerate видит только
те таблицы, чьи классы уже загружены к моменту сравнения со схемой базы.
Модель, забытая в этом списке, молча не попадёт в миграцию.
"""

from app.models.catalog import CatalogEntry
from app.models.document import Document, DocumentStatus, SourceFormat
from app.models.memory import (
    GlossaryEntryKind,
    GlossaryTerm,
    GlossaryTermStatus,
    TranslationUnit,
)
from app.models.organization import Membership, Organization, Role, User, UserStatus
from app.models.project import Project
from app.models.segment import Segment, SegmentKind, SegmentStatus
from app.models.session import RefreshSession
from app.models.terminology import TermCandidate, TermCandidateStatus

__all__ = [
    "CatalogEntry",
    "Document",
    "DocumentStatus",
    "GlossaryEntryKind",
    "GlossaryTerm",
    "GlossaryTermStatus",
    "Membership",
    "Organization",
    "Project",
    "RefreshSession",
    "Role",
    "Segment",
    "SegmentKind",
    "SegmentStatus",
    "SourceFormat",
    "TermCandidate",
    "TermCandidateStatus",
    "TranslationUnit",
    "User",
    "UserStatus",
]
