"""Главы книги: предложение, утверждение и правка границ."""

import uuid

from fastapi import APIRouter

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.chapter import Chapter
from app.schemas.chapter import (
    BookStructurePublic,
    ChapterPublic,
    ChapterRename,
    ChapterSplit,
    StructureSourcePublic,
)
from app.services.chapter_approval import BookStructure, ChapterApprovalService
from app.services.chapter_detection import ChapterDetectionService

router = APIRouter(tags=["chapters"])


@router.get("/books/{book_id}/chapters", response_model=BookStructurePublic)
async def book_structure(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BookStructurePublic:
    """Главы книги по порядку, их разделы и состав."""
    structure = await ChapterApprovalService(session, context).structure(book_id)

    return _structure(structure)


@router.post("/books/{book_id}/chapters/proposal", response_model=BookStructurePublic)
async def propose_chapters(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> BookStructurePublic:
    """Предложить главы по основному источнику.

    Прежнее предложение заменяется. Заново предлагать можно, пока ни одна
    глава не утверждалась: после утверждения у глав есть коды, и
    структуру правят разделением и объединением.
    """
    await ChapterDetectionService(session, context, storage).propose(book_id)

    return _structure(await ChapterApprovalService(session, context).structure(book_id))


@router.post("/books/{book_id}/chapters/approval", response_model=BookStructurePublic)
async def approve_all_chapters(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BookStructurePublic:
    """Утвердить границы всех черновиков по порядку книги."""
    service = ChapterApprovalService(session, context)
    await service.approve_all(book_id)

    return _structure(await service.structure(book_id))


@router.post("/chapters/{chapter_id}/approval", response_model=ChapterPublic)
async def approve_chapter(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> ChapterPublic:
    """Утвердить границы главы.

    Главы выше должны быть утверждены: код главы выдаётся при первом
    утверждении и по порядку книги.
    """
    chapter = await ChapterApprovalService(session, context).approve(chapter_id)

    return _chapter(chapter)


@router.post("/chapters/{chapter_id}/split", response_model=BookStructurePublic)
async def split_chapter(
    chapter_id: uuid.UUID, payload: ChapterSplit, context: ContextDep, session: SessionDep
) -> BookStructurePublic:
    """Разделить главу по началу одного из её разделов."""
    service = ChapterApprovalService(session, context)
    chapters = await service.split(chapter_id, at=payload.at)

    return _structure(await service.structure(chapters[0].book_id))


@router.post("/chapters/{chapter_id}/merge", response_model=BookStructurePublic)
async def merge_chapter(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BookStructurePublic:
    """Присоединить к главе следующую за ней."""
    service = ChapterApprovalService(session, context)
    chapters = await service.merge_next(chapter_id)

    return _structure(await service.structure(chapters[0].book_id))


@router.patch("/chapters/{chapter_id}", response_model=ChapterPublic)
async def rename_chapter(
    chapter_id: uuid.UUID, payload: ChapterRename, context: ContextDep, session: SessionDep
) -> ChapterPublic:
    """Назвать главу. Границ это не меняет, и утверждение остаётся в силе."""
    chapter = await ChapterApprovalService(session, context).rename(chapter_id, payload.title)

    return _chapter(chapter)


def _structure(structure: BookStructure) -> BookStructurePublic:
    return BookStructurePublic(
        chapters=[_chapter(chapter) for chapter in structure.chapters],
        source=(
            StructureSourcePublic.model_validate(structure.source)
            if structure.source is not None
            else None
        ),
        source_is_primary=structure.source_is_primary,
        can_propose=structure.can_propose,
    )


def _chapter(chapter: Chapter) -> ChapterPublic:
    return ChapterPublic.model_validate(chapter)
