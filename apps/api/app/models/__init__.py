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
from app.models.document import Document, SourceFormat, SourceRole
from app.models.glossary_version import (
    GlossaryScope,
    GlossaryVersion,
    GlossaryVersionChange,
    GlossaryVersionImpact,
    GlossaryVersionStatus,
    GlossaryVersionTerm,
    TermChangeKind,
)
from app.models.issue import (
    Issue,
    IssueAttachment,
    IssueCategory,
    IssueEvent,
    IssueEventKind,
    IssueSeverity,
    IssueStatus,
)
from app.models.job import JobKind, JobState, TranslationJob
from app.models.master import ChapterMaster
from app.models.memory import (
    FirstUseRule,
    GlossaryEntryKind,
    GlossaryTerm,
    GlossaryTermStatus,
    GlossaryUpload,
    TranslationUnit,
)
from app.models.notification import NotificationSettings
from app.models.organization import Membership, Organization, Role, User, UserStatus
from app.models.project import Project
from app.models.qa import (
    FindingDisposition,
    QAFinding,
    QAKind,
    QARun,
    QAScope,
    RevisionCheck,
)
from app.models.regression import (
    DependencyKind,
    RegressionDecision,
    RegressionItem,
    RegressionRun,
    RegressionStatus,
)
from app.models.session import RefreshSession
from app.models.shared import SharedTerm
from app.models.team import Invitation
from app.models.terminology import TermCandidate, TermCandidateStatus, TerminologyPass
from app.models.translation import (
    ObjectVerification,
    RevisionOrigin,
    RevisionStage,
    RunKind,
    TranslationRevision,
    TranslationRun,
)
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
    "FirstUseRule",
    "GlossaryEntryKind",
    "GlossaryScope",
    "GlossaryTerm",
    "GlossaryTermStatus",
    "GlossaryUpload",
    "GlossaryVersion",
    "GlossaryVersionChange",
    "GlossaryVersionImpact",
    "GlossaryVersionStatus",
    "GlossaryVersionTerm",
    "Invitation",
    "Issue",
    "IssueAttachment",
    "IssueCategory",
    "IssueEvent",
    "IssueEventKind",
    "IssueSeverity",
    "IssueStatus",
    "FindingDisposition",
    "QAFinding",
    "QAKind",
    "QARun",
    "QAScope",
    "RevisionCheck",
    "DependencyKind",
    "RegressionDecision",
    "RegressionItem",
    "RegressionRun",
    "RegressionStatus",
    "JobKind",
    "JobState",
    "Membership",
    "NotificationSettings",
    "ObjectReference",
    "ObjectType",
    "ObjectVerification",
    "Organization",
    "Project",
    "ReferenceKind",
    "RefreshSession",
    "RevisionOrigin",
    "RevisionStage",
    "Role",
    "RunKind",
    "SegmentChunk",
    "SharedTerm",
    "SourceFormat",
    "SourceRole",
    "SourceValidationResult",
    "TermCandidate",
    "TermCandidateStatus",
    "TermChangeKind",
    "TerminologyPass",
    "TranslationJob",
    "TranslationRevision",
    "TranslationRun",
    "TranslationUnit",
    "User",
    "UserStatus",
    "WorkspaceSettings",
]
