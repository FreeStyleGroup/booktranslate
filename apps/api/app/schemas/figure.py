"""Схемы перевода надписей на рисунках."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.figure import FigureStatus
from app.models.job import JobState

# Предел стороны картинки и координат: шире WebP и PNG на практике не бывают.
COORD_MAX = 100_000


class RegionEditPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    x: int = Field(ge=0, le=COORD_MAX)
    y: int = Field(ge=0, le=COORD_MAX)
    w: int = Field(ge=1, le=COORD_MAX)
    h: int = Field(ge=1, le=COORD_MAX)
    source_text: str = Field(min_length=1, max_length=500)
    target_text: str = Field(min_length=1, max_length=500)


class RegionsEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[RegionEditPublic] = Field(max_length=200)
    note: str | None = Field(default=None, max_length=4_000)


class KeepOriginal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=4_000)


class FigureTranslationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    status: FigureStatus
    regions: list[dict[str, Any]]
    needs_human: bool
    note: str | None
    has_asset: bool
    decided_at: datetime | None


class FigureImagePublic(BaseModel):
    object_id: uuid.UUID
    code: str
    index: int
    media_type: str
    current: FigureTranslationPublic | None


class ChapterFiguresPublic(BaseModel):
    images: list[FigureImagePublic]
    undecided: int
    job_state: JobState | None
    job_error: str | None
