"""Схемы версий глоссария и гейта терминологии."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.glossary_version import GlossaryScope, GlossaryVersionStatus, TermChangeKind
from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTermStatus
from app.schemas.book_object import BlockRefPublic


class GlossaryVersionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    book_id: uuid.UUID
    # Пусто у книжной версии.
    chapter_id: uuid.UUID | None
    scope: GlossaryScope
    number: int
    # `v3` — так версию называют люди.
    label: str
    status: GlossaryVersionStatus
    base_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None
    checksum: str
    term_count: int
    empty_reason: str | None
    created_by_id: uuid.UUID | None
    created_at: datetime
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None


class GateItemPublic(BaseModel):
    """Причина или предупреждение гейта: код для машины, фраза для человека."""

    code: str
    message: str
    chapter_id: uuid.UUID | None
    count: int | None


class GlossaryVersionDetailPublic(GlossaryVersionPublic):
    chapter_code: str | None
    # Что мешает утвердить черновик. У утверждённой и заменённой — пусто.
    blockers: list[GateItemPublic]
    # Сколько обязательных терминов изменилось против предыдущей
    # утверждённой версии и сколько блоков книги это задевает.
    changes: int
    impacted_blocks: int


class GlossaryDraftCreate(BaseModel):
    # Пусто — версия для всей книги.
    chapter_id: uuid.UUID | None = None


class GlossaryApproval(BaseModel):
    # Основание решения «терминов нет» — только для пустой версии.
    empty_reason: str | None = Field(default=None, max_length=1000)


class TerminologyPassPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    master_id: uuid.UUID
    actor_id: uuid.UUID | None
    min_frequency: int
    found: int
    created_at: datetime


class TerminologyGatePublic(BaseModel):
    """Готова ли глава к переводу с точки зрения терминов."""

    chapter_id: uuid.UUID
    chapter_code: str | None
    chapter_title: str | None
    ordinal: int
    open: bool
    # Действующая версия — по ней будут переводить.
    version: GlossaryVersionPublic | None
    # Черновик, который ждёт решения.
    draft: GlossaryVersionPublic | None
    blockers: list[GateItemPublic]
    warnings: list[GateItemPublic]
    master_id: uuid.UUID | None
    # Проход по нынешнему тексту главы — пусто, если его не было.
    current_pass: TerminologyPassPublic | None
    collected: bool
    undecided: int


class BookTerminologyPublic(BaseModel):
    """Терминология книги: гейт каждой главы и все версии глоссария."""

    chapters: list[TerminologyGatePublic]
    versions: list[GlossaryVersionPublic]


class VersionTermPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Запись рабочего словаря, из которой взят термин. Пусто — её удалили.
    term_id: uuid.UUID | None
    source_term: str
    target_term: str
    allowed_variants: list[str]
    kind: GlossaryEntryKind
    status: GlossaryTermStatus
    mandatory: bool
    case_sensitive: bool
    first_use_rule: FirstUseRule
    domain: str | None
    note: str | None
    reference: str | None


class VersionTermPagePublic(BaseModel):
    total: int
    items: list[VersionTermPublic]


class TermChangePublic(BaseModel):
    id: uuid.UUID
    source_term: str
    kind: TermChangeKind
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    # Сколько блоков книги задевает изменение.
    blocks: int


class ImpactedBlockPublic(BaseModel):
    block: BlockRefPublic
    chapter_id: uuid.UUID
    chapter_code: str | None
    # Изменённые термины, которые встречаются в блоке.
    terms: list[str]


class ImpactPagePublic(BaseModel):
    total: int
    items: list[ImpactedBlockPublic]
