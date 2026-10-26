"""Терминологический проход: по главе и, пока жив прежний контур, по документу."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContextDep, SessionDep
from app.models.terminology import TermCandidate, TermCandidateStatus
from app.schemas.terminology import (
    TermCandidatePublic,
    TermDecision,
    TermDecisionBatch,
    TerminologyReport,
)
from app.services.terminology import Decision, DecisionReport, TerminologyService

router = APIRouter(tags=["terminology"])

MinFrequency = Annotated[
    int, Query(ge=1, le=50, description="Сколько раз слово должно встретиться в тексте")
]
Limit = Annotated[int, Query(ge=1, le=2000)]


@router.post("/chapters/{chapter_id}/terminology/extract", response_model=list[TermCandidatePublic])
async def extract_chapter_terms(
    chapter_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    min_frequency: MinFrequency = 2,
    limit: Limit = 400,
) -> list[TermCandidatePublic]:
    """Собрать кандидатов в словарь из текста текущего мастера главы.

    Проход повторяемый: принятое и отклонённое остаётся, у нерешённого
    обновляются частота и пример. Каждый проход записывается вместе с
    версией мастера — версия глоссария утверждается только по главам, где
    кандидаты собраны по нынешнему тексту.
    """
    service = TerminologyService(session, context)
    candidates = await service.extract_chapter(chapter_id, min_frequency=min_frequency, limit=limit)

    return await _chapter_public(service, chapter_id, candidates)


@router.get("/chapters/{chapter_id}/terminology", response_model=list[TermCandidatePublic])
async def list_chapter_terms(
    chapter_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    status: Annotated[TermCandidateStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TermCandidatePublic]:
    """Кандидаты главы. Нерешённые идут первыми."""
    service = TerminologyService(session, context)
    candidates = await service.chapter_candidates(
        chapter_id, status=status, limit=limit, offset=offset
    )

    return await _chapter_public(service, chapter_id, candidates)


@router.post("/chapters/{chapter_id}/terminology/decisions", response_model=TerminologyReport)
async def decide_chapter_terms(
    chapter_id: uuid.UUID,
    payload: TermDecisionBatch,
    context: ContextDep,
    session: SessionDep,
) -> TerminologyReport:
    """Принять и отклонить кандидатов главы одной операцией.

    Принятый кандидат заводится в словарь проекта книги с пометкой
    `extracted`, отклонённый больше не показывается.
    """
    report = await TerminologyService(session, context).decide_chapter(
        chapter_id, [_decision(item) for item in payload.decisions]
    )

    return _report(report)


@router.post(
    "/documents/{document_id}/terminology/extract", response_model=list[TermCandidatePublic]
)
async def extract_terms(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    min_frequency: MinFrequency = 2,
    limit: Limit = 400,
) -> list[TermCandidatePublic]:
    """Собрать кандидатов из сегментов документа прежнего контура.

    Порог частоты подбирается под документ — на руководстве в тридцать
    страниц двойка нормальна, на книге в четыреста её стоит поднять, иначе
    список будет длиннее, чем человек разберёт.
    """
    candidates = await TerminologyService(session, context).extract(
        document_id, min_frequency=min_frequency, limit=limit
    )

    return [TermCandidatePublic.model_validate(candidate) for candidate in candidates]


@router.get("/documents/{document_id}/terminology", response_model=list[TermCandidatePublic])
async def list_terms(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    status: Annotated[TermCandidateStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TermCandidatePublic]:
    """Кандидаты документа. Нерешённые идут первыми."""
    candidates = await TerminologyService(session, context).document_candidates(
        document_id, status=status, limit=limit, offset=offset
    )

    return [TermCandidatePublic.model_validate(candidate) for candidate in candidates]


@router.post("/documents/{document_id}/terminology/decisions", response_model=TerminologyReport)
async def decide_terms(
    document_id: uuid.UUID,
    payload: TermDecisionBatch,
    context: ContextDep,
    session: SessionDep,
) -> TerminologyReport:
    """Принять и отклонить кандидатов документа одной операцией.

    Всё в одной транзакции: наполовину решённый словарь хуже нерешённого —
    по нему уже нельзя понять, где работа закончена.
    """
    report = await TerminologyService(session, context).decide(
        document_id, [_decision(item) for item in payload.decisions]
    )

    return _report(report)


async def _chapter_public(
    service: TerminologyService, chapter_id: uuid.UUID, candidates: list[TermCandidate]
) -> list[TermCandidatePublic]:
    codes = await service.first_codes(chapter_id, candidates)

    return [
        TermCandidatePublic.model_validate(candidate).model_copy(
            update={"first_block_code": codes.get(candidate.id)}
        )
        for candidate in candidates
    ]


def _decision(item: TermDecision) -> Decision:
    return Decision(
        candidate_id=item.candidate_id,
        accept=item.accept,
        target_term=item.target_term,
        kind=item.kind,
        mandatory=item.mandatory,
        note=item.note,
        reference=item.reference,
        status=item.status,
        first_use_rule=item.first_use_rule,
        allowed_variants=list(item.allowed_variants),
        domain=item.domain,
    )


def _report(report: DecisionReport) -> TerminologyReport:
    return TerminologyReport(
        accepted=report.accepted, rejected=report.rejected, remaining=report.remaining
    )
