"""Схемы глав и структуры книги."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.chapter import BoundaryStatus, ChapterOrigin
from app.models.document import SourceFormat

# Предел — от колонки: длиннее в базу всё равно не ляжет.
TITLE_MAX = 500


class SectionPublic(BaseModel):
    """Раздел главы: подзаголовок и состав до следующего подзаголовка."""

    # Номер первого блока — по нему главу и делят.
    start: int
    end: int
    level: int | None
    title: str | None
    locator: dict[str, Any]
    kinds: dict[str, int]


class ChapterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    book_id: uuid.UUID
    # Пусто, пока границы не утверждены ни разу: код выдаётся при
    # утверждении и дальше не меняется.
    code: str | None
    # Место в книге — меняется при разделении и объединении глав выше.
    ordinal: int
    title: str | None
    source_start: int
    source_end: int
    parser_version: str
    locator: dict[str, Any]
    origin: ChapterOrigin
    boundary_status: BoundaryStatus
    boundary_version: int
    approved_by_id: uuid.UUID | None
    approved_at: datetime | None
    sections: list[SectionPublic]
    # Сколько в главе блоков каждого вида. Блоков с постоянными кодами
    # ещё нет — они появятся при извлечении мастера; здесь состав по
    # разбору, и он показывает, что входит в утверждаемые границы.
    inventory: dict[str, int]


class StructureSourcePublic(BaseModel):
    """Файл, по номерам блоков которого размечены главы."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str | None
    source_format: SourceFormat


class BookStructurePublic(BaseModel):
    chapters: list[ChapterPublic]
    source: StructureSourcePublic | None
    # Ложно, если основной источник сменили после разметки: границы
    # заданы номерами блоков прежнего файла и к новому не подходят.
    source_is_primary: bool
    # Заново предложить можно, пока ни одна глава не получила кода.
    can_propose: bool


class ChapterSplit(BaseModel):
    # Номер первого блока раздела, с которого начнётся вторая часть.
    at: Annotated[int, Field(ge=1)]


class ChapterRename(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
