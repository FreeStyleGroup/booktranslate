"""Схемы перевода главы: готовность, прогоны, блоки и редакции."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.block import BlockKind
from app.models.job import JobState
from app.models.translation import RevisionOrigin, RevisionStage, RunKind
from app.schemas.glossary_version import GateItemPublic
from app.services.translation_runs import MAX_RETRANSLATE, REASON_MAX


class RejectionPublic(BaseModel):
    """Блок, ответ по которому отвергнут, и причина."""

    block_id: uuid.UUID
    code: str
    reason: str


class TranslationRunPublic(BaseModel):
    """Прогон: чем и по чему переводили, как идёт работа и сколько стоила."""

    id: uuid.UUID
    chapter_id: uuid.UUID
    master_id: uuid.UUID
    kind: RunKind
    provider: str
    model: str
    prompt_version: str
    glossary_version_id: uuid.UUID | None
    glossary_label: str | None
    ignore_terminology: bool
    bypass_reason: str | None
    requested_by_id: uuid.UUID | None
    # Состояние прогона — состояние его задания.
    job_id: uuid.UUID | None
    state: JobState | None
    error: str | None
    blocks_total: int
    blocks_done: int
    from_model: int
    from_memory: int
    copied: int
    rejections: list[RejectionPublic]
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ReadinessPublic(BaseModel):
    """Можно ли переводить главу: причины, предупреждения, сколько сделано."""

    chapter_id: uuid.UUID
    open: bool
    # Причины только о терминах: администратор вправе обойти гейт с причиной.
    bypassable: bool
    blockers: list[GateItemPublic]
    warnings: list[GateItemPublic]
    glossary_version_id: uuid.UUID | None
    glossary_label: str | None
    master_id: uuid.UUID | None
    master_label: str | None
    total: int
    translated: int
    pending: int
    live: TranslationRunPublic | None
    latest: TranslationRunPublic | None


class TranslationStart(BaseModel):
    """Запуск перевода. Обход гейта — только с причиной."""

    ignore_terminology: bool = False
    reason: str | None = Field(default=None, max_length=REASON_MAX)


class RetranslateItemIn(BaseModel):
    block_id: uuid.UUID
    # Редакция, рядом с которой нужен вариант, — та, что человек видел на экране.
    base_revision_id: uuid.UUID | None


class RetranslateRequest(TranslationStart):
    items: list[RetranslateItemIn] = Field(min_length=1, max_length=MAX_RETRANSLATE)


class RevisionBrief(BaseModel):
    """Редакция в списке блоков."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision_no: int
    stage: RevisionStage
    origin: RevisionOrigin
    text: str
    created_at: datetime


class ChapterBlockPublic(BaseModel):
    """Строка таблицы перевода: исходник, код и текущая редакция."""

    id: uuid.UUID
    code: str
    ordinal: int
    kind: BlockKind
    source_text: str
    protected: bool
    current: RevisionBrief | None
    variants: int


class ChapterBlockPage(BaseModel):
    total: int
    items: list[ChapterBlockPublic]


class ChangePublic(BaseModel):
    op: str
    text: str


class RevisionPublic(BaseModel):
    """Редакция в истории блока — с происхождением и сравнением."""

    id: uuid.UUID
    block_id: uuid.UUID
    revision_no: int
    stage: RevisionStage
    origin: RevisionOrigin
    text: str
    current: bool
    supersedes_id: uuid.UUID | None
    copied_from_id: uuid.UUID | None
    memory_unit_id: uuid.UUID | None
    run_id: uuid.UUID | None
    run_kind: RunKind | None
    model: str | None
    prompt_version: str | None
    glossary_version_id: uuid.UUID | None
    glossary_label: str | None
    ignore_terminology: bool
    author: str | None
    compared_with: int | None
    changes: list[ChangePublic]
    created_at: datetime


class BlockHistoryPublic(BaseModel):
    block_id: uuid.UUID
    code: str
    source_text: str
    active: bool
    # Защищённое содержимое: заново не переводится.
    protected: bool
    items: list[RevisionPublic]
