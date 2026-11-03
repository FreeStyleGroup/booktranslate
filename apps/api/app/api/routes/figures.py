"""Перевод надписей на рисунках: запуск, сверка рядом с оригиналом, решение."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status
from sqlalchemy import select

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.figure import FigureTranslation
from app.models.job import JobKind, TranslationJob
from app.schemas.figure import (
    ChapterFiguresPublic,
    FigureImagePublic,
    FigureTranslationPublic,
    KeepOriginal,
    RegionsEdit,
)
from app.services.figures import FigureImage, FigureService, RegionEdit

router = APIRouter(tags=["figures"])


def _translation(row: FigureTranslation) -> FigureTranslationPublic:
    return FigureTranslationPublic(
        id=row.id,
        version=row.version,
        status=row.status,
        regions=row.regions,
        needs_human=row.needs_human,
        note=row.note,
        has_asset=row.asset_key is not None,
        decided_at=row.decided_at,
    )


def _image(image: FigureImage) -> FigureImagePublic:
    return FigureImagePublic(
        object_id=image.object.id,
        code=image.code,
        index=image.index,
        media_type=image.media_type,
        current=_translation(image.current) if image.current is not None else None,
    )


@router.get("/chapters/{chapter_id}/figures", response_model=ChapterFiguresPublic)
async def chapter_figures(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ChapterFiguresPublic:
    service = FigureService(session, context, storage)
    images = await service.of_chapter(chapter_id)
    job = await session.scalar(
        select(TranslationJob)
        .where(
            TranslationJob.organization_id == context.organization_id,
            TranslationJob.chapter_id == chapter_id,
            TranslationJob.kind == JobKind.FIGURES,
        )
        .order_by(TranslationJob.created_at.desc())
        .limit(1)
    )

    return ChapterFiguresPublic(
        images=[_image(item) for item in images],
        undecided=len(await service.undecided(chapter_id)),
        job_state=job.state if job is not None else None,
        job_error=job.error if job is not None else None,
    )


@router.post(
    "/chapters/{chapter_id}/figures/translate",
    response_model=ChapterFiguresPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def translate_figures(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ChapterFiguresPublic:
    """Поставить чтение и перевод надписей в очередь."""
    await FigureService(session, context, storage).request(chapter_id)

    return await chapter_figures(chapter_id, context, session, storage)


@router.get("/figure-translations/{translation_id}/image")
async def figure_translation_image(
    translation_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> Response:
    """Файл с переводом. Только наш растр: заголовок запрещает браузеру угадывать тип."""
    content, media_type = await FigureService(session, context, storage).asset(translation_id)

    return Response(
        content=content,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )


@router.put("/figure-translations/{translation_id}/regions", response_model=FigureTranslationPublic)
async def edit_figure_regions(
    translation_id: uuid.UUID,
    payload: RegionsEdit,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> FigureTranslationPublic:
    """Поправить надписи: новая версия и новая перерисовка."""
    row = await FigureService(session, context, storage).edit(
        translation_id,
        [RegionEdit(**item.model_dump()) for item in payload.regions],
        note=payload.note,
    )

    return _translation(row)


@router.post(
    "/figure-translations/{translation_id}/approve", response_model=FigureTranslationPublic
)
async def approve_figure_translation(
    translation_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> FigureTranslationPublic:
    return _translation(await FigureService(session, context, storage).approve(translation_id))


@router.post(
    "/objects/{object_id}/images/{index}/keep-original", response_model=FigureTranslationPublic
)
async def keep_figure_original(
    object_id: uuid.UUID,
    index: Annotated[int, Path(ge=0, le=999)],
    payload: KeepOriginal,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> FigureTranslationPublic:
    """Оставить рисунок как в книге. Это тоже решение, и оно записывается."""
    row = await FigureService(session, context, storage).keep_original(
        object_id, index, note=payload.note
    )

    return _translation(row)
