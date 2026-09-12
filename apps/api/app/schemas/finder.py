"""Схемы общего поиска."""

import uuid

from pydantic import AliasPath, BaseModel, ConfigDict, Field

from app.models.segment import SegmentKind, SegmentStatus
from app.schemas.catalog import CatalogEntryPublic
from app.schemas.document import DocumentPublic
from app.schemas.glossary import GlossaryTermPublic


class SegmentHitPublic(BaseModel):
    """Сегмент в выдаче поиска — с книгой, в которой он стоит."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(validation_alias=AliasPath("segment", "id"))
    document_id: uuid.UUID = Field(validation_alias=AliasPath("segment", "document_id"))
    document_title: str
    position: int = Field(validation_alias=AliasPath("segment", "position"))
    kind: SegmentKind = Field(validation_alias=AliasPath("segment", "kind"))
    status: SegmentStatus = Field(validation_alias=AliasPath("segment", "status"))
    source_text: str = Field(validation_alias=AliasPath("segment", "source_text"))
    target_text: str | None = Field(validation_alias=AliasPath("segment", "target_text"))


class DocumentHits(BaseModel):
    total: int
    items: list[DocumentPublic]


class TermHits(BaseModel):
    total: int
    items: list[GlossaryTermPublic]


class EntryHits(BaseModel):
    total: int
    items: list[CatalogEntryPublic]


class SegmentHits(BaseModel):
    total: int
    items: list[SegmentHitPublic]


class SearchResult(BaseModel):
    """Четыре группы на один запрос. Общее число в каждой — по всей базе,
    показано — первые несколько."""

    query: str
    documents: DocumentHits
    terms: TermHits
    entries: EntryHits
    segments: SegmentHits
