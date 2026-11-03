"""Схемы общего поиска."""

import uuid

from pydantic import BaseModel

from app.models.block import BlockKind
from app.schemas.catalog import CatalogEntryPublic
from app.schemas.document import DocumentPublic
from app.schemas.glossary import GlossaryTermPublic


class BlockHitPublic(BaseModel):
    """Блок в выдаче поиска — с книгой и главой, где он стоит."""

    id: uuid.UUID
    book_id: uuid.UUID
    book_title: str
    chapter_id: uuid.UUID
    full_code: str
    kind: BlockKind
    source_text: str
    translation: str | None


class DocumentHits(BaseModel):
    total: int
    items: list[DocumentPublic]


class TermHits(BaseModel):
    total: int
    items: list[GlossaryTermPublic]


class EntryHits(BaseModel):
    total: int
    items: list[CatalogEntryPublic]


class BlockHits(BaseModel):
    total: int
    items: list[BlockHitPublic]


class SearchResult(BaseModel):
    """Четыре группы на один запрос. Общее число в каждой — по всей базе,
    показано — первые несколько."""

    query: str
    documents: DocumentHits
    terms: TermHits
    entries: EntryHits
    blocks: BlockHits
