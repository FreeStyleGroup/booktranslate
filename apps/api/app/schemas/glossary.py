"""Схемы глоссария и итога перевода."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import GlossaryEntryKind


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


class GlossaryTermPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    source_language: str
    target_language: str
    source_term: str
    target_term: str
    kind: GlossaryEntryKind
    note: str | None
    mandatory: bool
    case_sensitive: bool
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
