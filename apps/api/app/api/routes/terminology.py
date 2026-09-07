"""Терминологический проход по документу."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContextDep, SessionDep
from app.models.terminology import TermCandidateStatus
from app.schemas.terminology import (
    TermCandidatePublic,
    TermDecisionBatch,
    TerminologyReport,
)
from app.services.terminology import Decision, TerminologyService

router = APIRouter(tags=["terminology"])


@router.post(
    "/documents/{document_id}/terminology/extract", response_model=list[TermCandidatePublic]
)
async def extract_terms(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    min_frequency: Annotated[
        int,
        Query(ge=1, le=50, description="Сколько раз слово должно встретиться в документе"),
    ] = 2,
    limit: Annotated[int, Query(ge=1, le=2000)] = 400,
) -> list[TermCandidatePublic]:
    """Собрать кандидатов в словарь из текста документа.

    Проход повторяемый: принятое и отклонённое остаётся, у нерешённого
    обновляются частота и пример. Порог частоты подбирается под документ —
    на руководстве в тридцать страниц двойка нормальна, на книге в четыреста
    её стоит поднять, иначе список будет длиннее, чем человек разберёт.
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
    candidates = await TerminologyService(session, context).list(
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
    """Принять и отклонить кандидатов одной операцией.

    Принятый кандидат заводится в словарь проекта с пометкой `extracted`,
    отклонённый больше не показывается. Всё в одной транзакции: наполовину
    решённый словарь хуже нерешённого — по нему уже нельзя понять, где
    работа закончена.
    """
    report = await TerminologyService(session, context).decide(
        document_id,
        [
            Decision(
                candidate_id=item.candidate_id,
                accept=item.accept,
                target_term=item.target_term,
                kind=item.kind,
                mandatory=item.mandatory,
                note=item.note,
                reference=item.reference,
                status=item.status,
                expand_on_first_use=item.expand_on_first_use,
            )
            for item in payload.decisions
        ],
    )

    return TerminologyReport(
        accepted=report.accepted, rejected=report.rejected, remaining=report.remaining
    )
