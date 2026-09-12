"""Схемы каталога терминов."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import GlossaryEntryKind


class CatalogReference(BaseModel):
    """Источник справки."""

    title: str = ""
    url: str = ""


class CatalogEntryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_language: str
    target_language: str
    source_term: str
    # Нашлось ли. Ложь — это результат: по ней видно, что искали и не нашли,
    # и что второй раз спрашивать незачем.
    found: bool
    suggested_target: str | None
    definition: str | None
    expansion: str | None
    kind: GlossaryEntryKind
    sources: list[CatalogReference]
    # Чем справка получена: имя модели, ходившей в сеть, либо «offline».
    looked_up_by: str
    checked_at: datetime


class CatalogSourcePublic(BaseModel):
    """Чем отвечает справочник: имя модели с выходом в сеть либо «offline»."""

    name: str
    online: bool


class TermLookupRequest(BaseModel):
    """Спросить про слово, которого нет ни в словаре, ни в документе."""

    terms: list[str] = Field(min_length=1, max_length=50)
    source_language: str = Field(min_length=2, max_length=10)
    target_language: str = Field(min_length=2, max_length=10)

    # Отрывок, в котором слово встретилось. Не обязателен, но без него `head`
    # — это и «головка», и «оголовок».
    sample: str | None = Field(default=None, max_length=1000)
    # Предметная область: отрасль, название книги.
    subject: str | None = Field(default=None, max_length=300)

    # Спросить заново, даже если справка уже есть.
    refresh: bool = False


class DocumentLookupRequest(BaseModel):
    """Разобраться с кандидатами документа."""

    # Пусто — берутся самые частые из нерешённых: слово, встреченное сорок
    # раз, стоит справки больше, чем случайное из подписи к рисунку.
    candidate_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    limit: int | None = Field(default=None, ge=1, le=50)
    refresh: bool = False


class CatalogLookupReport(BaseModel):
    """Чем закончился прогон.

    Разделение на «взято из каталога» и «спрошено заново» — это ровно то,
    ради чего каталог существует: по нему видно, окупается ли он.
    """

    entries: list[CatalogEntryPublic]
    from_catalog: int
    asked: int
    found: int

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    # Поисковых запросов. Они оплачиваются отдельно от токенов, и в счётчиках
    # токенов их не видно вовсе.
    searches: int = 0
    # Оценка стоимости прогона. `null` — источник не в прейскуранте.
    estimated_usd: float | None = None
