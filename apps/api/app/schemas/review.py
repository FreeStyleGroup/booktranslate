"""Схемы редактуры и финальной сверки."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.models.issue import IssueSeverity, IssueStatus
from app.models.review import EditReason, ReviewKind, ReviewResult, ReviewStatus

NOTE_MAX = 4_000


class ReviewStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ReviewKind


class MarkBlock(BaseModel):
    """Отметка называет редакцию, которую человек видел."""

    model_config = ConfigDict(extra="forbid")

    block_id: uuid.UUID
    revision_id: uuid.UUID
    result: ReviewResult = ReviewResult.OK
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class MarkObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: uuid.UUID
    content_hash: str = Field(min_length=64, max_length=64)
    result: ReviewResult = ReviewResult.OK
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class LiteraryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: uuid.UUID
    base_revision_id: uuid.UUID
    text: str = Field(min_length=1, max_length=100_000)
    reason: EditReason
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    # Редактор видел предупреждение и настаивает: заведётся техническое замечание.
    accept_violation: bool = False
    # Замечание, по которому внесена правка, если оно есть. Того же блока.
    issue_id: uuid.UUID | None = None


class EditPreview(BaseModel):
    """Проверить правку до сохранения: предупредить проще, чем отказать."""

    model_config = ConfigDict(extra="forbid")

    block_id: uuid.UUID
    base_revision_id: uuid.UUID
    text: str = Field(min_length=1, max_length=100_000)


class EditPreviewResult(BaseModel):
    violations: list[str]


class ReviewRunPublic(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    book_title: str
    chapter_id: uuid.UUID
    chapter_title: str | None
    kind: ReviewKind
    status: ReviewStatus
    # Завершена автоматическим режимом: человек текст не смотрел.
    automatic: bool
    reviewer: str | None
    base_revision_set_hash: str
    completed_revision_set_hash: str | None
    completed_at: datetime | None
    created_at: datetime
    # Текст изменился после завершения: эта работа была про другой текст.
    stale: bool
    blocks_total: int
    blocks_done: int
    objects_total: int
    objects_done: int
    untranslated: int
    complete: bool


class LiteraryEditResult(BaseModel):
    run: ReviewRunPublic
    violations: list[str]


class ChapterReviewsPublic(BaseModel):
    technical: ReviewRunPublic | None
    literary: ReviewRunPublic | None
    final_compare: ReviewRunPublic | None


class NeighbourPublic(BaseModel):
    code: str
    ordinal: int
    source_text: str
    translation: str | None


class LinkedObjectPublic(BaseModel):
    """Объект рядом с блоком: блок в нём стоит или ссылается на него."""

    id: uuid.UUID
    chapter_id: uuid.UUID
    code: str
    type: ObjectType
    relation: str


class OpenIssuePublic(BaseModel):
    id: uuid.UUID
    code: str
    severity: IssueSeverity
    status: IssueStatus


class ReviewTermPublic(BaseModel):
    source: str
    target: str
    mandatory: bool


class NextBlockPublic(BaseModel):
    id: uuid.UUID
    code: str
    ordinal: int
    kind: BlockKind
    source_text: str
    revision_id: uuid.UUID
    revision_no: int
    text: str
    # Текст переносится знак в знак: стиль в нём не правится.
    protected: bool
    context: list[NeighbourPublic]
    terms: list[ReviewTermPublic]
    objects: list[LinkedObjectPublic]
    issues: list[OpenIssuePublic]


class NextObjectPublic(BaseModel):
    id: uuid.UUID
    code: str
    type: ObjectType
    content_hash: str
    # Место в списке объектов главы: от него продолжают, если объект пропущен.
    position: int
    source_text: str
    translation: str | None
    issues: list[OpenIssuePublic]


class NextItemPublic(BaseModel):
    """Следующее непросмотренное. Оба поля пусты — просмотрено всё."""

    block: NextBlockPublic | None
    object: NextObjectPublic | None
