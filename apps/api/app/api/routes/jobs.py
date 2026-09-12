"""Очередь заданий на перевод.

Книга переводится часами, и держать ради этого открытой вкладку нельзя.
Здесь её ставят в очередь и спрашивают, как идут дела; сам перевод делает
отдельный процесс (`python -m app.worker`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep
from app.schemas.job import TranslationJobPublic
from app.services.jobs import JobService

router = APIRouter(tags=["jobs"])


@router.post(
    "/documents/{document_id}/queue",
    response_model=TranslationJobPublic,
    status_code=status.HTTP_201_CREATED,
)
async def queue_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> TranslationJobPublic:
    """Поставить книгу в очередь на перевод.

    Отвечает заданием, а не переводом: перевод начнётся, когда до книги
    дойдёт очередь, и закончится через часы. За ходом следят по этому же
    заданию, а по готовности приходит уведомление.

    Одна книга — одно живое задание: повторная постановка той же книги
    отвечает отказом, а не заводит вторую очередь на неё.
    """
    job = await JobService(session, context).enqueue(document_id)

    return TranslationJobPublic.model_validate(job)


@router.get("/jobs", response_model=list[TranslationJobPublic])
async def list_jobs(
    context: ContextDep,
    session: SessionDep,
    document_id: Annotated[uuid.UUID | None, Query(description="Только задания этой книги")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TranslationJobPublic]:
    """Задания рабочего пространства — новые сверху."""
    jobs = await JobService(session, context).list(document_id=document_id, limit=limit)

    return [TranslationJobPublic.model_validate(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=TranslationJobPublic)
async def get_job(
    job_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> TranslationJobPublic:
    """Одно задание — по нему витрина рисует полосу выполнения."""
    job = await JobService(session, context).get(job_id)

    return TranslationJobPublic.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=TranslationJobPublic)
async def cancel_job(
    job_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> TranslationJobPublic:
    """Остановить задание.

    Остановка не отменяет сделанного: переведённое зафиксировано после
    каждой пачки, за него уже заплачено, и оно остаётся переведённым.
    Отменяется только продолжение.

    Работающее задание останавливается не мгновенно — рабочий смотрит на
    состояние между пачками, то есть в пределах одной пачки.
    """
    job = await JobService(session, context).cancel(job_id)

    return TranslationJobPublic.model_validate(job)
