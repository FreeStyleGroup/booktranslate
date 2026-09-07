"""Схемы глоссария и итога перевода."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import GlossaryEntryKind, GlossaryTermStatus


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
    # Раскрывать при первом употреблении: «маркет-мейкер (market maker, MM)»,
    # дальше просто MM.
    expand_on_first_use: bool = False


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
    expand_on_first_use: bool | None = None


class GlossaryTermPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    source_language: str
    target_language: str
    source_term: str
    target_term: str
    kind: GlossaryEntryKind
    status: GlossaryTermStatus
    note: str | None
    reference: str | None
    mandatory: bool
    case_sensitive: bool
    expand_on_first_use: bool
    # Откуда запись: «manual», «extracted», «import:<источник>». Нужна в
    # интерфейсе, чтобы отличить загруженную пачку от ручной работы.
    source: str
    created_at: datetime
    updated_at: datetime


class TranslationResult(BaseModel):
    """Чем закончился перевод документа.

    Цифры отдаются не для красоты: по ним считается, сколько обращений к
    модели не понадобилось, и они же обосновывают заказчику скидку на
    повторный заказ.
    """

    total: int
    from_memory: int
    from_provider: int
    flagged: int
    unique_texts: int
    # Обращений к провайдеру — против числа сегментов: разница и есть
    # экономия на повторах и памяти.
    provider_calls: int
    saved_calls: int
