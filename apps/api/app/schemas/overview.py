"""Схемы сводки по рабочему пространству."""

import uuid

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentProgress(BaseModel):
    id: uuid.UUID
    title: str
    status: DocumentStatus
    segments: int
    # Принято человеком. Готовность считается по принятому, а не по
    # переведённому: перевод, который никто не смотрел, готовым не является.
    done: int
    ready_percent: int


class FindingPreview(BaseModel):
    segment_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    position: int
    source_text: str
    target_text: str | None
    # Какие проверки не сошлись: числа, термины, подстановки, раскрытие.
    checks: list[str]


class UsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    # Оценка, а не счёт: у поставщика свои скидки и тарифы площадок.
    # `null` — модель не в прейскуранте.
    estimated_usd: float | None
    translated_by: str | None


class OverviewPublic(BaseModel):
    """Ответ на три вопроса, ради которых открывают кабинет.

    Что в работе, где меня ждут и во сколько это обошлось.
    """

    projects: int
    documents: int
    segments: int

    documents_by_status: dict[str, int]
    segments_by_status: dict[str, int]

    flagged: int
    undecided_terms: int

    glossary_terms: int
    catalog_entries: int
    memory_units: int

    usage: UsageSummary

    recent_documents: list[DocumentProgress]
    recent_findings: list[FindingPreview]
