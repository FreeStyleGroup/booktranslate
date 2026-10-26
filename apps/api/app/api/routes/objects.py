"""Специальные объекты главы: вкладки, карточка объекта, изображение, поиск по коду.

Ручек изменения нет: объекты появляются при извлечении мастера и
выводятся из действия при следующем.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.block import Block
from app.models.book_object import ObjectType
from app.models.chapter import Chapter
from app.schemas.book_object import (
    BlockRefPublic,
    FoundObjectPublic,
    MentionPublic,
    ObjectDetailPublic,
    ObjectPublic,
)
from app.services.book_objects import ObjectService, PlacedObject

router = APIRouter(tags=["objects"])

# Изображение из книги показывается как картинка и ничем больше: SVG,
# открытый по прямой ссылке, без запрета выполнил бы свои скрипты с
# домена сервиса. `sandbox` отнимает у него и скрипты, и формы, и
# переходы, а `default-src 'none'` — любые внешние загрузки.
_IMAGE_POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"

# Типы, которые браузер рисует. Остальное отдаётся на скачивание.
_SHOWN_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"})


@router.get("/masters/{master_id}/objects", response_model=list[ObjectPublic])
async def master_objects(
    master_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    type: Annotated[ObjectType | None, Query(description="Только объекты этого вида")] = None,
) -> list[ObjectPublic]:
    """Объекты версии мастера в её порядке — для вкладок главы."""
    listing = await ObjectService(session, context, storage).listing(master_id, kind=type)

    return [_listed(listing.chapter, item) for item in listing.objects]


@router.get("/objects/lookup", response_model=FoundObjectPublic)
async def find_object(
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    code: Annotated[str, Query(min_length=10, max_length=40)],
) -> FoundObjectPublic:
    """Объект по полному коду `BK01-CH03-FIG001` — где угодно в пространстве."""
    return await _found(ObjectService(session, context, storage), code, book_id=None)


@router.get("/books/{book_id}/objects/{code}", response_model=FoundObjectPublic)
async def find_object_in_book(
    book_id: uuid.UUID, code: str, context: ContextDep, session: SessionDep, storage: StorageDep
) -> FoundObjectPublic:
    """Объект по коду `CH03-FIG001` в пределах книги."""
    return await _found(ObjectService(session, context, storage), code, book_id=book_id)


@router.get("/objects/{object_id}", response_model=ObjectDetailPublic)
async def object_detail(
    object_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    master_id: Annotated[uuid.UUID | None, Query(description="Версия мастера")] = None,
) -> ObjectDetailPublic:
    """Объект: оригинал, подпись, содержимое и упоминания в тексте книги."""
    view = await ObjectService(session, context, storage).view(object_id, master_id=master_id)
    prefix = _prefix(view.chapter)
    placed = view.placed

    return ObjectDetailPublic(
        **_summary(placed, prefix, payload=placed.object.payload),
        book_id=view.chapter.book_id,
        master_id=view.master.id,
        master_label=view.master.label,
        content=[_block(block, prefix) for block in placed.content],
        caption_block=_block(placed.caption, prefix) if placed.caption is not None else None,
        mentions=[
            MentionPublic(
                block=_block(mention.block, _prefix(mention.chapter)),
                chapter_id=mention.chapter.id,
                kind=mention.reference.kind,
                phrase=mention.reference.phrase,
            )
            for mention in view.mentions
        ],
        parent_code=prefix + view.parent.code if view.parent is not None else None,
    )


@router.get("/objects/{object_id}/images/{index}")
async def object_image(
    object_id: uuid.UUID,
    index: int,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> StreamingResponse:
    """Изображение рисунка — оригинал, как он лежал в исходнике."""
    service = ObjectService(session, context, storage)
    image = await service.image(object_id, index)
    shown = image.media_type in _SHOWN_TYPES

    headers = {
        "Content-Disposition": "inline" if shown else "attachment",
        # Тип — определённый по байтам при извлечении, а не угаданный
        # браузером: угадывание и превращает «картинку» в страницу.
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": _IMAGE_POLICY,
        # Файл под ключом не меняется никогда: другое содержимое — другой
        # ключ. Поэтому его можно хранить в кеше браузера сколько угодно.
        "Cache-Control": "private, max-age=31536000, immutable",
    }
    if image.size is not None:
        headers["Content-Length"] = str(image.size)

    return StreamingResponse(
        service.stream(image),
        media_type=image.media_type if shown else "application/octet-stream",
        headers=headers,
    )


async def _found(
    service: ObjectService, code: str, *, book_id: uuid.UUID | None
) -> FoundObjectPublic:
    found = await service.find(code, book_id=book_id)

    return FoundObjectPublic(
        book_id=found.book.id,
        book_code=found.book.code,
        chapter_id=found.chapter.id,
        object_id=found.object.id,
        full_code=_prefix(found.chapter) + found.object.code,
    )


def _listed(chapter: Chapter, placed: PlacedObject) -> ObjectPublic:
    payload = dict(placed.object.payload)
    # Запись формулы как есть бывает в килобайты, а вкладке хватает дерева
    # для показа и текста.
    payload.pop("raw", None)

    return ObjectPublic(**_summary(placed, _prefix(chapter), payload=payload))


def _summary(placed: PlacedObject, prefix: str, *, payload: dict[str, Any]) -> dict[str, Any]:
    """Общее у строки вкладки и карточки объекта."""
    item = placed.object

    return {
        "id": item.id,
        "chapter_id": item.chapter_id,
        "code": item.code,
        "full_code": prefix + item.code,
        "type": item.type,
        "label": placed.placement.label,
        "checksum": item.checksum,
        "active": item.active,
        "at": placed.placement.at,
        "before_code": prefix + placed.before.code if placed.before is not None else None,
        "caption": placed.caption.source_text if placed.caption is not None else None,
        "caption_code": prefix + placed.caption.code if placed.caption is not None else None,
        "content_codes": [prefix + block.code for block in placed.content],
        "references": placed.references,
        "payload": payload,
    }


def _block(block: Block, prefix: str) -> BlockRefPublic:
    row = block.source_location.get("row")
    column = block.source_location.get("column")

    return BlockRefPublic(
        id=block.id,
        code=block.code,
        full_code=prefix + block.code,
        kind=block.kind,
        text=block.source_text,
        active=block.active,
        row=row if isinstance(row, int) else None,
        column=column if isinstance(column, int) else None,
    )


def _prefix(chapter: Chapter) -> str:
    # У главы с мастером код есть всегда: мастер извлекается только из
    # утверждённой главы, а код выдаётся при утверждении.
    return f"{chapter.code}-" if chapter.code is not None else ""
