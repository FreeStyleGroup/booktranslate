"""Разбор документа и просмотр сегментов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.schemas.document import DocumentPublic
from app.schemas.segment import SegmentPage, SegmentPublic
from app.services.parsing import ParsingService

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
) -> SegmentPage:
    service = ParsingService(session, context, storage)

    segments = await service.list_segments(document_id, limit=limit, offset=offset)
    total = await service.count_segments(document_id)

    return SegmentPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[SegmentPublic.model_validate(segment) for segment in segments],
    )
