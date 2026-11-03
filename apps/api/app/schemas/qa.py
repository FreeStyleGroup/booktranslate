"""Схемы проверок главы."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.issue import IssueCategory, IssueSeverity, IssueStatus
from app.models.job import JobState
from app.models.qa import FindingDisposition, QAKind, QAScope


class QAStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: QAKind


class QARunPublic(BaseModel):
    id: uuid.UUID
    chapter_id: uuid.UUID
    kind: QAKind
    scope: QAScope
    check_profile_version: str
    revision_set_hash: str
    model: str | None
    blocks_total: int
    blocks_checked: int
    blocks_untranslated: int
    findings_total: int
    issues_created: int
    rejections: list[dict[str, str]]
    input_tokens: int
    output_tokens: int
    job_id: uuid.UUID | None
    state: JobState | None
    error: str | None
    created_at: datetime


class ChapterChecksPublic(BaseModel):
    total: int
    translated: int
    # Отметки текущих редакций: два независимых индикатора.
    formal: int
    semantic: int
    # Сумма нынешнего текста: если прогон проверял другую, он уже не про этот текст.
    revision_set_hash: str
    latest_formal: QARunPublic | None
    latest_semantic: QARunPublic | None
    live: QARunPublic | None
    semantic_scope: QAScope


class QAFindingPublic(BaseModel):
    id: uuid.UUID
    qa_run_id: uuid.UUID
    book_id: uuid.UUID
    chapter_id: uuid.UUID
    block_id: uuid.UUID
    block_code: str
    revision_id: uuid.UUID
    kind: QAKind
    check: str
    message: str
    category: IssueCategory
    severity: IssueSeverity
    disposition: FindingDisposition
    rule: str | None
    issue_id: uuid.UUID | None
    issue_code: str | None
    issue_status: IssueStatus | None
    created_at: datetime


class QAFindingPage(BaseModel):
    total: int
    items: list[QAFindingPublic]
