"""Схемы заданий на перевод."""

import uuid
from datetime import datetime

from pydantic import AliasPath, BaseModel, ConfigDict, Field

from app.models.job import JobState


class TranslationJobPublic(BaseModel):
    """Задание таким, каким его видит человек.

    `worker` и `heartbeat_at` наружу не уходят: имя процесса и отметка
    жизни — устройство очереди, а не работа. Человеку важно другое —
    состояние, сколько сделано и почему сорвалось.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    # Название книги — из подгруженной вместе с заданием записи: список
    # заданий читают люди, а не программы, и «книга такая-то переведена»
    # без названия им не о чем.
    document_title: str = Field(validation_alias=AliasPath("document", "title"))
    state: JobState
    requested_by_id: uuid.UUID | None
    attempts: int
    error: str | None
    # Факты запуска: сколько было непереведённого, когда взялись, и сколько
    # перевели с тех пор.
    segments_total: int
    segments_done: int
    started_at: datetime | None
    finished_at: datetime | None
    notified_at: datetime | None
    created_at: datetime
    updated_at: datetime
