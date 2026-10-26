"""Схемы мастера главы и её блоков."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.block import BlockKind


class MasterCreate(BaseModel):
    # У первой версии причины нет; у каждой следующей она обязательна —
    # это проверяет сервис, потому что «первая ли» знает только он.
    reason: Annotated[str | None, Field(default=None, max_length=2000)]


class MasterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chapter_id: uuid.UUID
    version: int
    # `v2` — так версию называют в переписке и в журнале.
    label: str
    supersedes_id: uuid.UUID | None
    reason: str | None
    source_document_id: uuid.UUID
    parser_version: str
    boundary_version: int
    block_count: int
    object_count: int
    checksum: str
    created_by_id: uuid.UUID | None
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime


class BlockPublic(BaseModel):
    id: uuid.UUID
    chapter_id: uuid.UUID
    # `B0042` и полный `CH03-B0042`: полный — тот, что пишут в переписке.
    code: str
    full_code: str
    kind: BlockKind
    # Место блока в показываемой версии мастера.
    ordinal: int
    source_text: str
    source_location: dict[str, Any]
    source_hash: str
    active: bool
    # Код блока, из которого этот получился: правка или разделение абзаца
    # в новой версии мастера.
    parent_code: str | None
    chunks: int


class BlockPagePublic(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[BlockPublic]


class FoundBlockPublic(BaseModel):
    """Блок, найденный по коду, и где его показать."""

    book_id: uuid.UUID
    book_code: str
    chapter_id: uuid.UUID
    block: BlockPublic
    # Место в текущей версии мастера; пусто — блок выведен из действия.
    position: int | None
