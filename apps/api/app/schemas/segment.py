"""Схемы сегментов.

Наружу уходит и разметка положения в исходнике: по ней витрина показывает
редактору, с какой страницы или из какой главы сегмент, а без этого список
из тысячи абзацев теряет ориентиры.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.segment import SegmentKind, SegmentStatus


class SegmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    position: int
    kind: SegmentKind
    status: SegmentStatus
    source_text: str
    target_text: str | None
    source_location: dict[str, Any] | None
    quality: dict[str, Any] | None
    quality_score: float | None
    translation_source: str | None
    created_at: datetime
    updated_at: datetime


class SegmentPage(BaseModel):
    """Страница списка сегментов.

    Общее число отдаётся вместе со страницей: без него витрина не может
    показать ни полосу прокрутки, ни «переведено 120 из 3400», а считать его
    отдельным запросом на каждую прокрутку — лишний обход базы.
    """

    total: int
    limit: int
    offset: int
    items: list[SegmentPublic]
