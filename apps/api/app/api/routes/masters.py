"""Мастер главы и её блоки: версии, утверждение, блоки, поиск по коду.

Ручки «изменить текст мастера» здесь нет намеренно: мастер не правится.
Ошибка извлечения исправляется новой версией с причиной.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.block import Block
from app.models.chapter import Chapter
from app.schemas.master import (
    BlockPagePublic,
    BlockPublic,
    FoundBlockPublic,
    MasterCreate,
    MasterPublic,
)
from app.services.masters import MasterService

router = APIRouter(tags=["masters"])


@router.get("/chapters/{chapter_id}/masters", response_model=list[MasterPublic])
async def chapter_masters(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> list[MasterPublic]:
    """Версии мастера главы, новые первыми."""
    versions = await MasterService(session, context, storage).versions(chapter_id)

    return [MasterPublic.model_validate(master) for master in versions]


@router.post(
    "/chapters/{chapter_id}/masters",
    response_model=MasterPublic,
    status_code=status.HTTP_201_CREATED,
)
async def extract_master(
    chapter_id: uuid.UUID,
    payload: MasterCreate,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> MasterPublic:
    """Извлечь новую версию мастера главы.

    Глава должна быть с утверждёнными границами. Первая версия причины не
    требует, каждая следующая — требует. Неизменившиеся блоки сохраняют
    коды; если не изменилось ничего, версия не создаётся.
    """
    master = await MasterService(session, context, storage).extract(
        chapter_id, reason=payload.reason
    )

    return MasterPublic.model_validate(master)


@router.post("/masters/{master_id}/approval", response_model=MasterPublic)
async def approve_master(
    master_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> MasterPublic:
    """Подтвердить, что текущая версия мастера извлечена верно."""
    master = await MasterService(session, context, storage).approve(master_id)

    return MasterPublic.model_validate(master)


@router.get("/masters/{master_id}/blocks", response_model=BlockPagePublic)
async def master_blocks(
    master_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BlockPagePublic:
    """Блоки версии мастера в её порядке."""
    service = MasterService(session, context, storage)
    page = await service.blocks(master_id, limit=limit, offset=offset)
    chapter = await service.chapter_of(await service.get(master_id))

    return BlockPagePublic(
        total=page.total,
        limit=limit,
        offset=offset,
        # Место — в этой версии, а не текущее: прежняя версия обязана
        # показываться такой, какой была.
        items=await _blocks(
            service,
            chapter,
            page.items,
            ordinals=list(range(offset + 1, offset + 1 + len(page.items))),
        ),
    )


@router.get("/books/{book_id}/blocks/{code}", response_model=FoundBlockPublic)
async def find_block_in_book(
    book_id: uuid.UUID, code: str, context: ContextDep, session: SessionDep, storage: StorageDep
) -> FoundBlockPublic:
    """Блок по коду `CH03-B0042` — в какой бы главе и на какой странице он ни был."""
    return await _found(MasterService(session, context, storage), code, book_id=book_id)


@router.get("/blocks/lookup", response_model=FoundBlockPublic)
async def find_block(
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    code: Annotated[str, Query(min_length=8, max_length=40)],
) -> FoundBlockPublic:
    """Блок по полному коду `BK01-CH03-B0042` — где угодно в пространстве."""
    return await _found(MasterService(session, context, storage), code, book_id=None)


async def _found(
    service: MasterService, code: str, *, book_id: uuid.UUID | None
) -> FoundBlockPublic:
    found = await service.find(code, book_id=book_id)
    [block] = await _blocks(service, found.chapter, [found.block], ordinals=[found.block.ordinal])

    return FoundBlockPublic(
        book_id=found.book.id,
        book_code=found.book.code,
        chapter_id=found.chapter.id,
        block=block,
        position=found.position,
    )


async def _blocks(
    service: MasterService, chapter: Chapter, blocks: list[Block], *, ordinals: list[int]
) -> list[BlockPublic]:
    """Блоки с полными кодами, кодами предков и числом частей.

    Место передаётся снаружи: у блока хранится место в текущей версии, а
    показывать его могут в любой.

    Полный код собирается здесь, а не хранится: он состоит из кода главы
    и кода блока, и третья запись того же значения однажды разошлась бы с
    первыми двумя.
    """
    # У главы с мастером код есть всегда: мастер извлекается только из
    # утверждённой главы, а код выдаётся при утверждении.
    prefix = f"{chapter.code}-" if chapter.code is not None else ""
    parents = await service.parents(blocks)
    chunks = await service.chunks([block.id for block in blocks])

    return [
        BlockPublic(
            id=block.id,
            chapter_id=block.chapter_id,
            code=block.code,
            full_code=prefix + block.code,
            kind=block.kind,
            ordinal=ordinal,
            source_text=block.source_text,
            source_location=block.source_location,
            source_hash=block.source_hash,
            active=block.active,
            parent_code=(
                prefix + parents[block.parent_block_id].code
                if block.parent_block_id is not None and block.parent_block_id in parents
                else None
            ),
            chunks=chunks.get(block.id, 0),
        )
        for block, ordinal in zip(blocks, ordinals, strict=True)
    ]
