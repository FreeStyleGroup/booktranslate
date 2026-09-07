"""Схемы терминологического прохода."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.models.terminology import TermCandidateStatus


class TermCandidatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    source_term: str
    kind: GlossaryEntryKind
    status: TermCandidateStatus
    frequency: int
    # Кусок текста вокруг первого вхождения: решать по голому списку слов
    # нельзя, значение термина видно только в контексте.
    sample: str
    # Номер сегмента первого вхождения: спор о термине решается возвратом
    # к этому месту.
    first_position: int
    # Расшифровка аббревиатуры, найденная в самом документе.
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
    expand_on_first_use: bool | None = None


class TermDecisionBatch(BaseModel):
    # Верхняя граница — не каприз: пачка применяется одной транзакцией, и
    # запрос на десять тысяч решений держал бы её открытой минутами.
    decisions: list[TermDecision] = Field(min_length=1, max_length=500)


class TerminologyReport(BaseModel):
    accepted: int
    rejected: int
    # Пока больше нуля, документ к переводу не готов: непринятое решение —
    # это термин, который модель придумает сама и по-разному.
    remaining: int
