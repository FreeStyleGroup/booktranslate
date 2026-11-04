"""Схемы финальных версий глав и выпусков книги."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.issue import IssueSeverity
from app.models.job import JobState
from app.models.release import ArtifactFormat, BookReleaseStatus, PageStatus, ReleaseStatus
from app.schemas.chapter_translation import ChangePublic


class BlockerPublic(BaseModel):
    code: str
    message: str
    count: int | None = None


class ReleaseGatePublic(BaseModel):
    ready: bool
    blockers: list[BlockerPublic]


class ChapterReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Новая старшая версия: v2.0 вместо v1.1.
    major: bool = False


class ChapterReleasePublic(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    chapter_id: uuid.UUID
    code: str
    version: str
    status: ReleaseStatus
    automatic: bool
    manifest_hash: str
    blocks: int
    objects: int
    creator: str | None
    approver: str | None
    approved_at: datetime | None
    created_at: datetime
    # Рабочий текст ушёл вперёд от этой версии.
    working_differs: bool


class ManifestPublic(BaseModel):
    manifest: dict[str, Any]
    manifest_hash: str
    # Сумма сошлась с содержимым: запись не менялась.
    intact: bool


class WorkingChangePublic(BaseModel):
    block_id: uuid.UUID
    code: str
    final_text: str | None
    working_text: str | None
    changes: list[ChangePublic]


class AssemblyVersionPublic(BaseModel):
    id: uuid.UUID
    code: str
    version: str


class AssemblyItemPublic(BaseModel):
    chapter_id: uuid.UUID
    chapter_code: str | None
    title: str | None
    ordinal: int
    chosen_id: uuid.UUID | None
    available: list[AssemblyVersionPublic]
    working_differs: bool


class AssemblyProblemPublic(BaseModel):
    code: str
    severity: str
    message: str
    chapter_id: uuid.UUID | None


class TocEntryPublic(BaseModel):
    chapter_code: str | None
    level: int
    text: str


class AssemblyPublic(BaseModel):
    ready: bool
    items: list[AssemblyItemPublic]
    problems: list[AssemblyProblemPublic]
    toc: list[TocEntryPublic]


class BookReleaseCreate(BaseModel):
    """Версии глав называются явно: «последняя» — только подсказка экрана."""

    model_config = ConfigDict(extra="forbid")

    chapter_release_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    major: bool = False


class BookReleasePublic(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    title: str
    code: str
    version: str
    status: BookReleaseStatus
    manifest_hash: str
    chapters: list[dict[str, Any]]
    toc: list[TocEntryPublic]
    created_at: datetime
    # Ложь, если такой состав уже был собран и вернулась прежняя запись.
    created: bool = True


class ArtifactPublic(BaseModel):
    id: uuid.UUID
    format: ArtifactFormat
    checksum: str
    size: int
    renderer_version: str
    manifest_hash: str
    page_count: int | None
    superseded_at: datetime | None
    created_at: datetime


class ReleaseFilesPublic(BaseModel):
    artifacts: list[ArtifactPublic]
    previous: list[ArtifactPublic]
    job_state: JobState | None
    job_error: str | None


class PageAuditPublic(BaseModel):
    page_no: int
    status: PageStatus
    issue_id: uuid.UUID | None
    checked_at: datetime | None


class PageIssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: IssueSeverity = IssueSeverity.MAJOR
    description: str = Field(min_length=1, max_length=10_000)


class PageIssueResult(BaseModel):
    page: PageAuditPublic
    issue_id: uuid.UUID
    issue_code: str


class GateCheckPublic(BaseModel):
    code: str
    title: str
    passed: bool


class GateBlockerPublic(BaseModel):
    check: str
    code: str
    message: str
    count: int | None
    chapter_id: uuid.UUID | None
    issue_id: uuid.UUID | None
    page_no: int | None


class GatePublic(BaseModel):
    release_id: uuid.UUID
    code: str
    status: BookReleaseStatus
    ready: bool
    # Подтверждён автоматическим режимом: глазами выпуск никто не смотрел.
    automatic: bool
    checks: list[GateCheckPublic]
    blockers: list[GateBlockerPublic]
    passed_at: datetime | None
    # Снимок проверки на момент PASS.
    snapshot: dict[str, Any] | None
