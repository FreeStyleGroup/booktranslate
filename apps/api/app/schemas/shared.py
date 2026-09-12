"""Схемы общего словаря площадки и загрузок словарей."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import GlossaryEntryKind
from app.schemas.glossary import GlossaryTermPublic
from app.schemas.workspace import SubjectPublic


class GlossaryUploadPublic(BaseModel):
    """Запись о загрузке словаря — глазами пространства."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    origin: str
    source_language: str
    target_language: str
    project_id: uuid.UUID | None
    total: int
    added: int
    updated: int
    skipped: int
    # Под каким разрешением прошла: отдана площадке или нет.
    shared: bool
    created_at: datetime


class DictionaryImportResult(BaseModel):
    """Чем закончилась загрузка словаря."""

    total: int
    added: int
    updated: int
    skipped: int
    # Причины пропуска, а не одно число: по ним видно, перепутаны ли колонки
    # местами и тот ли файл загрузили.
    reasons: list[str]
    upload: GlossaryUploadPublic


class SharedTermPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    source_language: str
    target_language: str
    source_term: str
    target_term: str
    kind: GlossaryEntryKind
    note: str | None
    created_at: datetime


class SuggestionsPublic(BaseModel):
    """Подсказки пространству из общего словаря."""

    # Тематика пространства; пусто — подсказок нет, и надо сказать почему.
    subject: str | None
    items: list[SharedTermPublic]


# ── Администратор площадки ──


class AdminUploadPublic(BaseModel):
    """Загрузка в ленте администратора."""

    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    uploaded_by: str | None
    filename: str
    origin: str
    source_language: str
    target_language: str
    total: int
    added: int
    updated: int
    skipped: int
    shared: bool
    # Тематика пространства — с ней термины и предлагаются в общий словарь.
    subject: str | None
    reviewed_at: datetime | None
    reviewed_by: str | None
    created_at: datetime


class AdminUploadList(BaseModel):
    items: list[AdminUploadPublic]
    # Сколько ещё не смотрели: ради этого числа лента и открывается.
    unreviewed: int
    subjects: list[SubjectPublic]


class AdminUploadDetail(BaseModel):
    upload: AdminUploadPublic
    terms: list[GlossaryTermPublic]
    subjects: list[SubjectPublic]


class PublishRequest(BaseModel):
    term_ids: list[uuid.UUID] = Field(max_length=5000)
    subject: str = Field(min_length=1, max_length=60)


class PublishedPublic(BaseModel):
    published: int


class SharedListPublic(BaseModel):
    total: int
    items: list[SharedTermPublic]
    subjects: list[SubjectPublic]
