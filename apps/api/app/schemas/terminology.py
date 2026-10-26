"""Схемы терминологического прохода."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTermStatus
from app.models.terminology import TermCandidateStatus
from app.schemas.glossary import Variant


class TermCandidatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Владелец — ровно один: документ прежнего контура или глава.
    document_id: uuid.UUID | None
    chapter_id: uuid.UUID | None
    source_term: str
    kind: GlossaryEntryKind
    status: TermCandidateStatus
    frequency: int
    # Кусок текста вокруг первого вхождения: решать по голому списку слов
    # нельзя, значение термина видно только в контексте.
    sample: str
    # Место первого вхождения — номер сегмента или место блока в мастере:
    # спор о термине решается возвратом к этому месту.
    first_position: int
    first_block_id: uuid.UUID | None
    # Код этого блока (`CH03-B0042`) — у кандидатов главы.
    first_block_code: str | None = None
    # Расшифровка аббревиатуры, найденная в самом тексте.
    expansion: str | None
    glossary_term_id: uuid.UUID | None


class TermDecision(BaseModel):
    candidate_id: uuid.UUID
    accept: bool = True
    # У непереводимого перевод совпадает с исходником, и требовать его
    # значило бы заставлять человека копировать строку.
    target_term: str | None = Field(default=None, max_length=300)
    kind: GlossaryEntryKind | None = None
    mandatory: bool = True
    note: str | None = None
    # Чем решение обосновано: справочник, стандарт, адрес страницы.
    reference: str | None = None
    status: GlossaryTermStatus = GlossaryTermStatus.CONFIRMED
    # None — «по умолчанию для вида»: аббревиатуру принято раскрывать при
    # первом употреблении, обычный термин — нет.
    first_use_rule: FirstUseRule | None = None
    allowed_variants: list[Variant] = Field(default_factory=list, max_length=20)
    domain: str | None = Field(default=None, max_length=120)


class TermDecisionBatch(BaseModel):
    # Верхняя граница — не каприз: пачка применяется одной транзакцией, и
    # запрос на десять тысяч решений держал бы её открытой минутами.
    decisions: list[TermDecision] = Field(min_length=1, max_length=500)


class TerminologyReport(BaseModel):
    accepted: int
    rejected: int
    # Пока больше нуля, терминология не готова: непринятое решение — это
    # термин, который модель придумает сама и по-разному.
    remaining: int
