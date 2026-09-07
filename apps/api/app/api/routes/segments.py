"""Разбор документа и просмотр сегментов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.segment import SegmentStatus
from app.schemas.document import DocumentPublic
from app.schemas.segment import (
    ApprovedCount,
    ReviewProgress,
    SegmentEdit,
    SegmentEdited,
    SegmentPage,
    SegmentPublic,
)
from app.services.parsing import ParsingService
from app.services.review import ReviewService

router = APIRouter(tags=["segments"])


@router.post("/documents/{document_id}/parse", response_model=DocumentPublic)
async def parse_document(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    force: Annotated[
        bool,
        Query(description="Разобрать заново, удалив существующие сегменты вместе с переводом"),
    ] = False,
) -> DocumentPublic:
    """Разобрать документ на сегменты.

    Отвечает документом, а не списком сегментов: их могут быть десятки тысяч,
    и отдавать их все в ответ на запуск разбора незачем — за ними идут
    постранично отдельной ручкой. Итог разбора виден по статусу: `parsed` —
    получилось, `failed` — нет, и тогда причина в поле `error`.
    """
    document = await ParsingService(session, context, storage).parse(document_id, force=force)

    return DocumentPublic.model_validate(document)


@router.get("/documents/{document_id}/segments", response_model=SegmentPage)
async def list_segments(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[
        list[SegmentStatus] | None,
        Query(description="Отобрать по состоянию; можно указать несколько раз"),
    ] = None,
    worst_first: Annotated[
        bool,
        Query(description="Сначала сегменты с худшей оценкой проверок, а не по порядку в книге"),
    ] = False,
) -> SegmentPage:
    """Сегменты документа.

    Редактор смотрит не книгу подряд, а очередь замечаний, поэтому здесь
    есть и отбор по состоянию, и порядок «сначала худшее».
    """
    service = ParsingService(session, context, storage)

    segments = await service.list_segments(
        document_id, limit=limit, offset=offset, statuses=status, worst_first=worst_first
    )
    total = await service.count_segments(document_id, statuses=status)

    return SegmentPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[SegmentPublic.model_validate(segment) for segment in segments],
    )


@router.get("/documents/{document_id}/progress", response_model=ReviewProgress)
async def document_progress(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> ReviewProgress:
    """Сколько сделано по документу.

    Отдельной ручкой, а не полем документа: считается по сегментам, и
    держать эти числа в самом документе значило бы обновлять их при каждой
    правке и однажды разойтись с действительностью.
    """
    progress = await ReviewService(session, context).progress(document_id)

    return ReviewProgress(
        total=progress.total,
        translated=progress.translated,
        flagged=progress.flagged,
        edited=progress.edited,
        approved=progress.approved,
        untouched=progress.untouched,
        is_complete=progress.is_complete,
    )


@router.patch("/segments/{segment_id}", response_model=SegmentEdited)
async def edit_segment(
    segment_id: uuid.UUID,
    payload: SegmentEdit,
    context: ContextDep,
    session: SessionDep,
) -> SegmentEdited:
    """Записать правку редактора.

    Правка расходится по непринятым повторам того же текста в этом
    документе — одинаковый исходник обязан звучать одинаково — и попадает в
    память переводов как человеческая, вытесняя оттуда машинный вариант.
    Сегменты, которые человек уже правил или принял, не трогаются.
    """
    result = await ReviewService(session, context).edit(segment_id, payload.target_text)

    return SegmentEdited(
        segment=SegmentPublic.model_validate(result.segment),
        propagated=result.propagated,
    )


@router.post("/segments/{segment_id}/approve", response_model=SegmentPublic)
async def approve_segment(
    segment_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> SegmentPublic:
    """Принять сегмент.

    Принять сегмент с находками можно: проверка машинная и ошибается, а
    отвечает за текст человек. Находки при этом сохраняются — видно, что
    именно было замечено и всё-таки принято.
    """
    segment = await ReviewService(session, context).approve(segment_id)

    return SegmentPublic.model_validate(segment)


@router.post("/segments/{segment_id}/reopen", response_model=SegmentPublic)
async def reopen_segment(
    segment_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> SegmentPublic:
    """Вернуть принятый сегмент в работу."""
    segment = await ReviewService(session, context).reopen(segment_id)

    return SegmentPublic.model_validate(segment)


@router.post("/documents/{document_id}/segments/approve-clean", response_model=ApprovedCount)
async def approve_clean(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> ApprovedCount:
    """Принять всё, к чему у проверок нет претензий.

    Без этого приёмка книги — три тысячи нажатий, и делать её никто не
    станет. Помеченное проверками остаётся редактору: смысл разделения в
    том, чтобы его внимание доставалось спорному, а не всему подряд.
    """
    approved = await ReviewService(session, context).approve_clean(document_id)

    return ApprovedCount(approved=approved)
