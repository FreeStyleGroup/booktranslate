"""Схемы заданий на перевод."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.job import JobKind, JobState


class TranslationJobPublic(BaseModel):
    """Задание таким, каким его видит человек.

    `worker` и `heartbeat_at` наружу не уходят: имя процесса и отметка
    жизни — устройство очереди, а не работа. Человеку важно другое —
    состояние, сколько сделано и почему сорвалось.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: JobKind
    chapter_id: uuid.UUID
    book_id: uuid.UUID
    run_id: uuid.UUID
    # Название книги — из подгруженной вместе с заданием записи: список
    # заданий читают люди, а не программы, и «книга такая-то переведена»
    # без названия им не о чем.
    title: str
    state: JobState
    requested_by_id: uuid.UUID | None
    attempts: int
    error: str | None
    # Факты запуска: сколько было непереведённого, когда взялись, и сколько
    # перевели с тех пор.
    items_total: int
    items_done: int
    started_at: datetime | None
    finished_at: datetime | None
    notified_at: datetime | None
    created_at: datetime
    updated_at: datetime
