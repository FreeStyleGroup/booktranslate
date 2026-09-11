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


class CostEstimate(BaseModel):
    """Смета на перевод — оценка сверху, а не счёт.

    Точного числа токенов заранее не знает никто, поэтому здесь заведомо
    осторожная оценка (см. app/services/pricing.py). Показывать её надо
    именно так, как она названа: числом порядка, а не суммой к оплате.
    `usd` пуст, если модель не в прейскуранте, — это честнее нуля.
    """

    model_config = ConfigDict(from_attributes=True)

    input_tokens: int
    output_tokens: int
    usd: float | None


class DocumentProfilePublic(BaseModel):
    """Паспорт документа: из чего он состоит и во что обойдётся перевод."""

    model_config = ConfigDict(from_attributes=True)

    segments: int
    characters: int
    words: int
    longest_segment_chars: int

    by_kind: dict[str, int]
    by_status: dict[str, int]

    untranslated: int
    unique_untranslated: int
    repeated: int
    memory_matches: int
    # Кандидатов в словарь: всего и без решения. Пока нерешённые есть,
    # перевод не начнётся. Два числа, а не одно: ноль нерешённых означает и
    # «всё решено», и «проход не делался вовсе» — состояния разные.
    terms_total: int
    undecided_terms: int

    billable_texts: int
    billable_characters: int

    estimate: CostEstimate | None
