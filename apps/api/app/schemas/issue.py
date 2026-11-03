"""Схемы реестра ошибок.

Поля регистрации перечислены явно и лишние отвергаются: кода, снимков, статуса и автора
клиент прислать не может. Молчаливо проигнорированное поле выглядело бы как принятое.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.issue import IssueCategory, IssueEventKind, IssueSeverity, IssueStatus

TEXT_MAX = 10_000
NOTE_MAX = 4_000

Note = Annotated[str, Field(min_length=1, max_length=NOTE_MAX)]


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    category: IssueCategory
    severity: IssueSeverity
    description: str = Field(min_length=1, max_length=TEXT_MAX)
    proposed_fix: str | None = Field(default=None, max_length=TEXT_MAX)
    parent_issue_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None


class OptionalNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=NOTE_MAX)


class RequiredNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note


class IssueFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: uuid.UUID
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class IssueReclassify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Note
    category: IssueCategory | None = None
    severity: IssueSeverity | None = None


class IssueAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: uuid.UUID | None


class IssuePublic(BaseModel):
    id: uuid.UUID
    code: str
    book_id: uuid.UUID
    book_title: str
    chapter_id: uuid.UUID
    block_id: uuid.UUID | None
    block_code: str | None
    object_id: uuid.UUID | None
    object_code: str | None
    parent_issue_id: uuid.UUID | None
    category: IssueCategory
    severity: IssueSeverity
    status: IssueStatus
    priority_score: int
    impact_count: int
    automatic: bool
    detected_by: str | None
    assignee_id: uuid.UUID | None
    assignee: str | None
    description: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IssuePagePublic(BaseModel):
    total: int
    items: list[IssuePublic]


class IssueStatsPublic(BaseModel):
    total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_category: dict[str, int]
    open_critical: int
    open_major: int


class IssueEventPublic(BaseModel):
    id: uuid.UUID
    kind: IssueEventKind
    from_status: IssueStatus | None
    to_status: IssueStatus | None
    actor: str | None
    note: str | None
    related_revision_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime


class IssueNeighbourPublic(BaseModel):
    block_id: uuid.UUID
    code: str
    source_text: str
    translation: str | None


class IssueTermPublic(BaseModel):
    source: str
    target: str
    mandatory: bool
    note: str | None


class IssueObjectPublic(BaseModel):
    id: uuid.UUID
    code: str
    type: str


class IssueCandidatePublic(BaseModel):
    revision_id: uuid.UUID
    revision_no: int
    block_code: str
    text: str


class IssueAttachmentPublic(BaseModel):
    id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime


class IssueBrief(BaseModel):
    id: uuid.UUID
    code: str
    status: IssueStatus


class IssueDetailPublic(IssuePublic):
    chapter_label: str | None
    source_snapshot: str
    target_snapshot: str | None
    proposed_fix: str | None
    discovered_revision_id: uuid.UUID | None
    fix_revision_id: uuid.UUID | None
    current_revision_id: uuid.UUID | None
    current_text: str | None
    # Текст мог уйти из текущей версии мастера: проверяющий должен это видеть.
    subject_active: bool
    context: list[IssueNeighbourPublic]
    terms: list[IssueTermPublic]
    objects: list[IssueObjectPublic]
    events: list[IssueEventPublic]
    attachments: list[IssueAttachmentPublic]
    candidates: list[IssueCandidatePublic]
    children: list[IssueBrief]
    parent: IssueBrief | None
    # Что можно сделать с этим замечанием прямо сейчас этому человеку.
    actions: list[str]
    review_note: str | None
