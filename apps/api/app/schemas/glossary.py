"""Схемы глоссария и итога перевода."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTermStatus

# Допустимый вариант перевода — та же строка словаря, что и сам перевод.
Variant = Annotated[str, Field(min_length=1, max_length=300)]


class GlossaryTermCreate(BaseModel):
    source_term: str = Field(min_length=1, max_length=300)
    target_term: str = Field(min_length=1, max_length=300)
    source_language: str = Field(min_length=2, max_length=10)
    target_language: str = Field(min_length=2, max_length=10)

    # Термин проекта или общий для организации. По умолчанию общий: словарь
    # бюро наполняется чаще, чем словарь одного заказа.
    project_id: uuid.UUID | None = None
    kind: GlossaryEntryKind = GlossaryEntryKind.TERM
    note: str | None = None
    mandatory: bool = True
    # None означает «по умолчанию для вида»: у аббревиатур регистр значим,
    # у обычных терминов — нет.
    case_sensitive: bool | None = None
    # Заведённое руками считается решённым: человек, набравший перевод, уже
    # договорился с собой. Бюро, ведущее два прохода по словарю, ставит
    # PROPOSED и подтверждает вторым проходом.
    status: GlossaryTermStatus = GlossaryTermStatus.CONFIRMED
    # Чем решение обосновано: справочник, стандарт, адрес страницы, где
    # термин посмотрели.
    reference: str | None = None
    # Что сделать при первом употреблении: раскрыть сокращение —
    # «маркет-мейкер (market maker, MM)», дальше просто MM, — или дать
    # оригинал в скобках.
    first_use_rule: FirstUseRule = FirstUseRule.NONE
    # Согласованные варианты перевода помимо основного.
    allowed_variants: list[Variant] = Field(default_factory=list, max_length=20)
    # Предметная область, где решение верно: «гидравлика», «электропривод».
    domain: str | None = Field(default=None, max_length=120)


class GlossaryTermUpdate(BaseModel):
    """Правка записи. Присылается только то, что меняется.

    Все поля необязательны, и различие «не прислано» и «прислано пустым»
    здесь значимое: первое оставляет значение как есть, второе стирает
    примечание или источник.
    """

    target_term: str | None = Field(default=None, min_length=1, max_length=300)
    kind: GlossaryEntryKind | None = None
    status: GlossaryTermStatus | None = None
    note: str | None = None
    reference: str | None = None
    mandatory: bool | None = None
    case_sensitive: bool | None = None
    first_use_rule: FirstUseRule | None = None
    allowed_variants: list[Variant] | None = Field(default=None, max_length=20)
    domain: str | None = Field(default=None, max_length=120)


class GlossaryTermPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    source_language: str
    target_language: str
    source_term: str
    target_term: str
    allowed_variants: list[str]
    domain: str | None
    kind: GlossaryEntryKind
    status: GlossaryTermStatus
    note: str | None
    reference: str | None
    mandatory: bool
    case_sensitive: bool
    first_use_rule: FirstUseRule
    # Откуда запись: «manual», «extracted», «platform», «import:<источник>».
    # Нужна в интерфейсе, чтобы отличить загруженную пачку от ручной работы.
    source: str
    upload_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class GlossaryPagePublic(BaseModel):
    """Страница словаря: сколько всего подходит под отбор и что показано."""

    total: int
    items: list[GlossaryTermPublic]
