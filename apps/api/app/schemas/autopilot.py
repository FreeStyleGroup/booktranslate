"""Схемы автоматического режима."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.autopilot import AutopilotStatus


class AutopilotStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Кандидат становится термином, если встретился не реже этого числа раз.
    term_min_frequency: int = Field(default=5, ge=2, le=1000)
    # Смысловая сверка тратит токены, но заменяет глаза редактора хотя бы отчасти.
    semantic: bool = True
    # Предел сметы перевода. Пусто — без предела.
    budget_usd: float | None = Field(default=None, gt=0, le=1_000_000)


class AutopilotResume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_usd: float | None = Field(default=None, gt=0, le=1_000_000)


class AutopilotStagePublic(BaseModel):
    code: str
    title: str
    # done, current или pending.
    state: str


class AutopilotReasonPublic(BaseModel):
    code: str
    message: str
    chapter_id: uuid.UUID | None
    issue_id: uuid.UUID | None
    figures: bool
    release_id: uuid.UUID | None


class AutopilotPublic(BaseModel):
    id: uuid.UUID
    book_id: uuid.UUID
    status: AutopilotStatus
    stage: str
    stages: list[AutopilotStagePublic]
    waiting: list[AutopilotReasonPublic]
    profile: dict[str, Any]
    chapters_total: int
    chapters_done: int
    release_id: uuid.UUID | None
    finished_at: datetime | None
    created_at: datetime


class AutopilotState(BaseModel):
    """Состояние по книге. Пусто — автоматический режим по ней не запускали."""

    run: AutopilotPublic | None
