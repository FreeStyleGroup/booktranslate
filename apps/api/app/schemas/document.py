"""Схемы документов.

Наружу не уходит ключ хранилища: он описывает внутреннее устройство и по
нему нечего делать клиенту — файл отдаётся отдельной ручкой по
идентификатору документа.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus, SourceFormat


class DocumentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    original_filename: str | None
    source_format: SourceFormat
    status: DocumentStatus
    size_bytes: int | None
    # Контрольная сумма отдаётся клиенту сознательно: по ней он понимает,
    # что загрузка вернула уже существующий документ, а не завела новый.
    content_hash: str | None
    error: str | None

    # Потрачено на перевод документа нарастающим итогом по всем запускам.
    # Токены, а не деньги: цены меняются, а потраченное на эту книгу —
    # исторический факт, и пересчитывать его задним числом нельзя.
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    # Чем переведён документ: по нему считается стоимость и понятно, что
    # перепроверять после смены модели.
    translated_by: str | None

    created_at: datetime
    updated_at: datetime
