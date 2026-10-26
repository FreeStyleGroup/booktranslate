"""Объекты главы для чтения: вкладки рисунков, таблиц, формул и кода.

Объекты не правятся: они появляются при извлечении мастера и выводятся
из действия при следующем. Здесь — только то, как их показать: в составе
версии мастера, по одному со всем, что к ним относится, и по коду.
"""

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book import BookEdition
from app.models.book_object import CODE_PREFIXES, BookObject, ObjectReference, ObjectType
from app.models.chapter import Chapter
from app.models.master import ChapterMaster
from app.services.base import TenantService
from app.services.books import BookService
from app.services.context import RequestContext
from app.services.errors import InvalidInputError, NotFoundError
from app.services.object_extraction import picture_key
from app.services.storage import ObjectStorage

_TYPES_BY_PREFIX = {prefix: kind for kind, prefix in CODE_PREFIXES.items()}

# Код объекта, как его называют люди: `CH03-FIG001` в пределах книги или
# `BK01-CH03-FIG001` где угодно в пространстве.
_OBJECT_CODE = re.compile(
    rf"^(?:BK(?P<book>\d+)-)?CH(?P<chapter>\d+)-(?P<prefix>{'|'.join(_TYPES_BY_PREFIX)})"
    r"(?P<number>\d+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Placement:
    """Где объект стоит в версии мастера и из чего состоит."""

    at: int
    content: list[uuid.UUID]
    caption: uuid.UUID | None
    label: str | None

    @classmethod
    def of(cls, entry: dict[str, Any]) -> "Placement":
        caption = entry.get("caption")

        return cls(
            at=int(entry["at"]),
            content=[uuid.UUID(item) for item in entry.get("blocks", [])],
            caption=uuid.UUID(caption) if caption else None,
            label=entry.get("label"),
        )


@dataclass(frozen=True, slots=True)
class PlacedObject:
    """Объект в составе версии мастера — со своими блоками в этой версии."""

    object: BookObject
    placement: Placement
    content: list[Block]
    caption: Block | None
    # Блок, перед которым объект стоит; пусто — объект в конце главы.
    before: Block | None
    references: int


@dataclass(frozen=True, slots=True)
class ObjectListing:
    chapter: Chapter
    objects: list[PlacedObject]


@dataclass(frozen=True, slots=True)
class Mention:
    block: Block
    chapter: Chapter
    reference: ObjectReference


@dataclass(frozen=True, slots=True)
class ObjectView:
    """Объект со всем, что к нему относится, — в одной версии мастера."""

    placed: PlacedObject
    chapter: Chapter
    master: ChapterMaster
    mentions: list[Mention]
    parent: BookObject | None


@dataclass(frozen=True, slots=True)
class FoundObject:
    book: BookEdition
    chapter: Chapter
    object: BookObject


@dataclass(frozen=True, slots=True)
class StoredImage:
    key: str
    media_type: str
    size: int | None


class ObjectService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def listing(
        self, master_id: uuid.UUID, *, kind: ObjectType | None = None
    ) -> ObjectListing:
        """Объекты версии мастера в её порядке — все или одного вида."""
        master = await self._master(master_id)
        ids = [uuid.UUID(entry["id"]) for entry in master.objects]

        found = {
            item.id: item
            for item in await self._session.scalars(
                self.scoped(BookObject).where(BookObject.id.in_(ids))
            )
        }
        chosen = [
            found[item]
            for item in ids
            if item in found and (kind is None or found[item].type is kind)
        ]

        return ObjectListing(
            chapter=await self._chapter(master.chapter_id),
            objects=await self._placed(master, chosen),
        )

    async def view(self, object_id: uuid.UUID, *, master_id: uuid.UUID | None) -> ObjectView:
        """Объект в версии мастера — заданной или последней, где он есть.

        Без версии показывается последняя, в которую объект входит: у
        действующего это текущая, у выведенного — та, где он был в
        последний раз. Иначе выведенный объект показался бы без подписи и
        без содержимого, хотя и то и другое у него было.
        """
        item = await self.get(object_id)
        master = (
            await self._master(master_id) if master_id is not None else await self._holder(item)
        )

        if master.chapter_id != item.chapter_id or not any(
            entry["id"] == str(item.id) for entry in master.objects
        ):
            raise NotFoundError("Объекта нет в этой версии мастера")

        parent = (
            await self._session.scalar(
                self.scoped(BookObject).where(BookObject.id == item.parent_object_id)
            )
            if item.parent_object_id is not None
            else None
        )
        [placed] = await self._placed(master, [item])

        return ObjectView(
            placed=placed,
            chapter=await self._chapter(item.chapter_id),
            master=master,
            mentions=await self._mentions(item.id),
            parent=parent,
        )

    async def _placed(self, master: ChapterMaster, objects: list[BookObject]) -> list[PlacedObject]:
        """Объекты с их блоками в этой версии — одним запросом за блоками."""
        entries = {entry["id"]: Placement.of(entry) for entry in master.objects}
        placements = [entries[str(item.id)] for item in objects]

        def before(placement: Placement) -> uuid.UUID | None:
            """Первый блок после объекта — не его собственный: ячейки и
            подпись стоят сразу за местом объекта, но «перед своей
            подписью» о месте таблицы ничего не говорит."""
            own = {str(block) for block in (*placement.content, placement.caption) if block}
            following = (item for item in master.block_ids[placement.at :] if item not in own)
            found = next(following, None)
            return uuid.UUID(found) if found is not None else None

        blocks = await self._blocks(
            {
                block
                for placement in placements
                for block in (*placement.content, placement.caption, before(placement))
                if block is not None
            }
        )
        counts = await self._reference_counts([item.id for item in objects])

        def block(block_id: uuid.UUID | None) -> Block | None:
            return blocks.get(block_id) if block_id is not None else None

        return [
            PlacedObject(
                object=item,
                placement=placement,
                content=[blocks[part] for part in placement.content if part in blocks],
                caption=block(placement.caption),
                before=block(before(placement)),
                references=counts.get(item.id, 0),
            )
            for item, placement in zip(objects, placements, strict=True)
        ]

    async def get(self, object_id: uuid.UUID) -> BookObject:
        item = await self._session.scalar(self.scoped(BookObject).where(BookObject.id == object_id))

        if item is None:
            raise NotFoundError("Объект не найден")

        return item

    async def find(self, code: str, *, book_id: uuid.UUID | None) -> FoundObject:
        """Объект по коду — в книге (`CH03-FIG001`) или в пространстве (`BK01-CH03-FIG001`).

        Находится и выведенный из действия: на него ссылаются прежние версии
        мастера и замечания.
        """
        match = _OBJECT_CODE.match(code.strip())

        if match is None:
            raise InvalidInputError("Код объекта выглядит так: CH03-FIG001 или BK01-CH03-TBL002")

        if book_id is not None:
            book = await BookService(self._session, self._context).get(book_id)
        elif match.group("book") is not None:
            found_book = await self._session.scalar(
                self.scoped(BookEdition).where(BookEdition.number == int(match.group("book")))
            )
            if found_book is None:
                raise NotFoundError(f"Книга BK{int(match.group('book')):02d} не найдена")
            book = found_book
        else:
            raise InvalidInputError("Вне книги код объекта нужен целиком: BK01-CH03-FIG001")

        chapter = await self._session.scalar(
            self.scoped(Chapter).where(
                Chapter.book_id == book.id, Chapter.number == int(match.group("chapter"))
            )
        )
        item = (
            await self._session.scalar(
                self.scoped(BookObject).where(
                    BookObject.chapter_id == chapter.id,
                    BookObject.type == _TYPES_BY_PREFIX[match.group("prefix").upper()],
                    BookObject.number == int(match.group("number")),
                )
            )
            if chapter is not None
            else None
        )

        if chapter is None or item is None:
            raise NotFoundError(f"Объект {code.strip().upper()} не найден")

        return FoundObject(book=book, chapter=chapter, object=item)

    async def image(self, object_id: uuid.UUID, index: int) -> StoredImage:
        """Изображение рисунка: где лежит и каким типом его отдавать."""
        item = await self.get(object_id)
        images = item.payload.get("images", []) if item.type is ObjectType.FIGURE else []

        if not 0 <= index < len(images) or not images[index].get("sha256"):
            raise NotFoundError("Изображения нет: в исходнике оно не нашлось")

        entry = images[index]

        return StoredImage(
            key=picture_key(self.organization_id, entry["sha256"]),
            media_type=entry.get("media_type") or "application/octet-stream",
            size=entry.get("size"),
        )

    def stream(self, image: StoredImage) -> AsyncIterator[bytes]:
        return self._storage.stream(image.key)

    async def chapter_of(self, item: BookObject) -> Chapter:
        return await self._chapter(item.chapter_id)

    async def _holder(self, item: BookObject) -> ChapterMaster:
        """Последняя версия мастера главы, в которую объект входит."""
        master: ChapterMaster | None = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(
                ChapterMaster.chapter_id == item.chapter_id,
                ChapterMaster.objects.contains([{"id": str(item.id)}]),
            )
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )

        if master is None:
            raise NotFoundError("Объекта нет ни в одной версии мастера")

        return master

    async def _mentions(self, object_id: uuid.UUID) -> list[Mention]:
        """Где объект упомянут — в действующем тексте книги, по порядку глав и блоков."""
        rows = await self._session.execute(
            select(ObjectReference, Block, Chapter)
            .join(Block, Block.id == ObjectReference.block_id)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .where(
                ObjectReference.organization_id == self.organization_id,
                ObjectReference.object_id == object_id,
                Block.active.is_(True),
            )
            .order_by(Chapter.ordinal, Block.ordinal)
        )

        return [
            Mention(block=block, chapter=chapter, reference=reference)
            for reference, block, chapter in rows.tuples()
        ]

    async def _reference_counts(self, object_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not object_ids:
            return {}

        rows = await self._session.execute(
            select(ObjectReference.object_id, func.count())
            .join(Block, Block.id == ObjectReference.block_id)
            .where(
                ObjectReference.organization_id == self.organization_id,
                ObjectReference.object_id.in_(object_ids),
                Block.active.is_(True),
            )
            .group_by(ObjectReference.object_id)
        )

        return {object_id: count for object_id, count in rows.tuples()}

    async def _blocks(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, Block]:
        if not ids:
            return {}

        return {
            block.id: block
            for block in await self._session.scalars(self.scoped(Block).where(Block.id.in_(ids)))
        }

    async def _master(self, master_id: uuid.UUID) -> ChapterMaster:
        master = await self._session.scalar(
            self.scoped(ChapterMaster).where(ChapterMaster.id == master_id)
        )

        if master is None:
            raise NotFoundError("Версия мастера не найдена")

        return master

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))

        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter
