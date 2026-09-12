"""Схемы заданий на перевод."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
