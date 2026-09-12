"""Схемы памяти переводов."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TranslationUnitPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_language: str
    target_language: str
    source_text: str
    target_text: str
    # Откуда перевод: имя модели либо «human». По нему видно, чему доверять.
    origin: str
    # Сколько раз пара пригодилась — то есть сколько раз за неё не платили.
    hits: int
    created_at: datetime
    updated_at: datetime


class MemorySummaryPublic(BaseModel):
    """Чего память стоит. Деньги — оценка сверху по текущей модели."""

    model_config = ConfigDict(from_attributes=True)

    units: int
    human_units: int
    hits: int
    saved_characters: int
    saved_usd: float | None


class MemoryPagePublic(BaseModel):
    total: int
    items: list[TranslationUnitPublic]
    summary: MemorySummaryPublic


class TranslationUnitUpdate(BaseModel):
    target_text: str = Field(min_length=1, max_length=20_000)
