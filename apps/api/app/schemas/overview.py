"""Схемы сводки по рабочему пространству."""

import uuid

from pydantic import BaseModel


class BookProgress(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    blocks: int
    # Блоков с текущей редакцией перевода.
    translated: int
    ready_percent: int


class AttentionPreview(BaseModel):
    """Прогон, которому нужен человек."""

    run_id: uuid.UUID
    book_id: uuid.UUID
    chapter_id: uuid.UUID
    title: str
    problem: str


class UsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    # Оценка, а не счёт: у поставщика свои скидки и периоды. `null` — ни одна
    # из моделей не в прейскуранте.
    estimated_usd: float | None


class OverviewPublic(BaseModel):
    """Ответ на три вопроса, ради которых открывают кабинет.

    Что в работе, где меня ждут и во сколько это обошлось.
    """

    projects: int
    books: int
    documents: int

    blocks: int
    translated: int
    by_origin: dict[str, int]

    live_runs: int
    undecided_terms: int

    glossary_terms: int
    catalog_entries: int
    memory_units: int

    usage: UsageSummary

    recent_books: list[BookProgress]
    attention: list[AttentionPreview]
