"""Упоминания объектов в тексте: «см. рис. 3.2» и гиперссылки на рисунок.

Упоминание — производное: текст блока неизменяем, и что он упоминает,
зависит только от текста и от того, какие объекты есть в книге сейчас.
Поэтому упоминания книги пересчитываются целиком при каждом извлечении
мастера любой её главы: глава 3 ссылается на рисунок главы 5, и связь
появляется, когда извлечена пятая, а не третья.

Гиперссылка надёжнее номера: автор сам указал, куда она ведёт. Номер
находится по тексту и выбирается так: объект с этим номером в той же
главе, а если в главе такого нет — единственный такой в книге. Два
рисунка «3.2» в разных главах при упоминании из третьей — не догадка, а
неизвестность, и связи нет.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select

from app.models.block import Block
from app.models.book_object import BookObject, ObjectReference, ObjectType, ReferenceKind
from app.models.chapter import Chapter
from app.services.base import TenantService
from app.services.parsers.labels import mentions

# Колонка фразы — от разумной длины упоминания, а не от длины абзаца.
PHRASE_MAX = 200


@dataclass(frozen=True, slots=True)
class TextBlock:
    id: uuid.UUID
    chapter_id: uuid.UUID
    text: str
    links: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnownObject:
    id: uuid.UUID
    chapter_id: uuid.UUID
    type: ObjectType
    label: str | None
    anchors: tuple[str, ...]
    # Подпись объекта упоминает его номер, но ссылкой на него не является.
    caption_block_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class FoundReference:
    block_id: uuid.UUID
    object_id: uuid.UUID
    kind: ReferenceKind
    phrase: str


def find_references(
    blocks: Iterable[TextBlock], objects: Sequence[KnownObject]
) -> list[FoundReference]:
    """Какие блоки какие объекты упоминают."""
    by_anchor = {anchor: item for item in objects for anchor in item.anchors}
    by_label: dict[tuple[ObjectType, str], list[KnownObject]] = defaultdict(list)

    for item in objects:
        if item.label is not None:
            by_label[(item.type, item.label)].append(item)

    found: list[FoundReference] = []

    for block in blocks:
        pairs: dict[uuid.UUID, FoundReference] = {}

        for mention in mentions(block.text):
            target = _pick(by_label.get((mention.type, mention.number), []), block.chapter_id)
            if target is not None and target.caption_block_id != block.id:
                pairs.setdefault(
                    target.id,
                    FoundReference(
                        block_id=block.id,
                        object_id=target.id,
                        kind=ReferenceKind.LABEL,
                        phrase=mention.phrase[:PHRASE_MAX],
                    ),
                )

        for link in block.links:
            target = by_anchor.get(link)
            if target is None or target.caption_block_id == block.id:
                continue

            # Ссылка и номер на один объект — одна связь, и она ссылка.
            # Фраза остаётся словами текста, если они нашлись.
            earlier = pairs.get(target.id)
            pairs[target.id] = FoundReference(
                block_id=block.id,
                object_id=target.id,
                kind=ReferenceKind.LINK,
                phrase=earlier.phrase if earlier is not None else _fragment(link),
            )

        found.extend(pairs.values())

    return found


def _pick(candidates: list[KnownObject], chapter_id: uuid.UUID) -> KnownObject | None:
    same_chapter = [item for item in candidates if item.chapter_id == chapter_id]

    if len(same_chapter) == 1:
        return same_chapter[0]

    if not same_chapter and len(candidates) == 1:
        return candidates[0]

    return None


def _fragment(link: str) -> str:
    """`#fig3-2` — как ссылку видно в разметке, без пути к файлу."""
    return ("#" + link.rpartition("#")[2])[:PHRASE_MAX]


class ObjectReferenceService(TenantService):
    async def refresh(self, book_id: uuid.UUID) -> int:
        """Пересчитать упоминания объектов книги. Транзакцией управляет вызывающий."""
        chapters = select(Chapter.id).where(
            Chapter.organization_id == self.organization_id, Chapter.book_id == book_id
        )

        objects = [
            KnownObject(
                id=item.id,
                chapter_id=item.chapter_id,
                type=item.type,
                label=item.label,
                anchors=tuple(item.source_location.get("anchors") or ()),
                caption_block_id=item.caption_block_id,
            )
            for item in await self._session.scalars(
                self.scoped(BookObject).where(
                    BookObject.chapter_id.in_(chapters), BookObject.active.is_(True)
                )
            )
        ]

        rows = await self._session.execute(
            select(Block.id, Block.chapter_id, Block.source_text, Block.source_location).where(
                Block.organization_id == self.organization_id,
                Block.chapter_id.in_(chapters),
                Block.active.is_(True),
            )
        )
        blocks = (
            TextBlock(
                id=block_id,
                chapter_id=chapter_id,
                text=text,
                links=tuple(location.get("links") or ()),
            )
            for block_id, chapter_id, text, location in rows.tuples()
        )

        found = find_references(blocks, objects) if objects else []

        await self._session.execute(
            delete(ObjectReference).where(
                ObjectReference.organization_id == self.organization_id,
                ObjectReference.object_id.in_(
                    select(BookObject.id).where(BookObject.chapter_id.in_(chapters))
                ),
            )
        )
        self._session.add_all(
            ObjectReference(
                organization_id=self.organization_id,
                block_id=item.block_id,
                object_id=item.object_id,
                kind=item.kind,
                phrase=item.phrase,
            )
            for item in found
        )

        return len(found)
