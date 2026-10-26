"""Мастер главы: извлечение версий, утверждение, блоки, поиск по коду.

Операции «изменить текст мастера» здесь нет и не будет: мастер — снимок
исходника, и ошибка извлечения исправляется новой версией с причиной, а
авторская ошибка в тексте — замечанием. Всё, что меняется, меняется
появлением новой записи, а не правкой старой.
"""

import asyncio
import os
import re
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.block import Block, SegmentChunk
from app.models.book import BookEdition
from app.models.book_object import BookObject, ObjectType
from app.models.chapter import Chapter
from app.models.coding import CodeKind
from app.models.document import Document
from app.models.master import ChapterMaster
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.block_reconcile import (
    AnchorNotFoundError,
    Create,
    Existing,
    Fresh,
    Keep,
    PlacedEntry,
    Retire,
    Step,
    block_hash,
    locate,
    master_checksum,
    match,
    object_hash,
    reconcile,
)
from app.services.books import MANAGING_ROLES, BookService
from app.services.chapter_approval import ChapterApprovalService
from app.services.chapter_detection import sections_of
from app.services.chunking import chunk, estimate_tokens
from app.services.coding import CodeAllocator
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.object_extraction import (
    Described,
    Picture,
    describe,
    in_chapter,
    picture_key,
    read_pictures,
)
from app.services.object_references import ObjectReferenceService
from app.services.parsers import (
    PARSER_VERSION,
    DocumentParser,
    ImageSource,
    ParsedBlock,
    ParsedSource,
    ParsingError,
    PlacedObject,
    collect,
    parser_for,
)
from app.services.pricing import SOURCE_CHARS_PER_TOKEN
from app.services.source_files import local_copy
from app.services.storage import ObjectStorage

# Причина новой версии — не формальность: по ней через год объясняют,
# почему текст главы в выпуске отличается от первого извлечения.
REASON_MIN = 10
REASON_MAX = 1000

# Код блока, как его называют люди: `CH03-B0042` в пределах книги или
# `BK01-CH03-B0042` где угодно в пространстве.
_BLOCK_CODE = re.compile(
    r"^(?:BK(?P<book>\d+)-)?CH(?P<chapter>\d+)-B(?P<block>\d+)$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class BlockPage:
    """Блоки версии мастера по порядку — страница из общего числа."""

    total: int
    items: list[Block]


@dataclass(frozen=True, slots=True)
class FoundBlock:
    """Найденный по коду блок и то, где его показать.

    `position` — место блока в текущей версии мастера главы; пусто, если
    блок выведен из действия и живёт только в прежних версиях.
    """

    book: BookEdition
    chapter: Chapter
    block: Block
    position: int | None


class MasterService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def versions(self, chapter_id: uuid.UUID) -> list[ChapterMaster]:
        """Версии мастера главы, новые первыми."""
        chapter = await self._chapter(chapter_id)

        return list(
            await self._session.scalars(
                self.scoped(ChapterMaster)
                .where(ChapterMaster.chapter_id == chapter.id)
                .order_by(ChapterMaster.version.desc())
            )
        )

    async def get(self, master_id: uuid.UUID) -> ChapterMaster:
        master = await self._session.scalar(
            self.scoped(ChapterMaster).where(ChapterMaster.id == master_id)
        )

        if master is None:
            raise NotFoundError("Версия мастера не найдена")

        return master

    async def extract(self, chapter_id: uuid.UUID, *, reason: str | None) -> ChapterMaster:
        """Извлечь новую версию мастера главы из её исходника.

        Первая версия причины не требует. Каждая следующая — требует: версия
        без причины неотличима от тихой правки исходника.

        Блоки и объекты сопоставляются с прежней версией: неизменившиеся
        сохраняют коды, изменённые получают новые с родством, исчезнувшие
        выводятся из действия. Если ничего не изменилось, версия не
        создаётся — она была бы копией прежней под новым номером.
        """
        self._context.require(*MANAGING_ROLES)

        approval = ChapterApprovalService(self._session, self._context)
        chapter = await approval.require_approved(chapter_id)
        book = await BookService(self._session, self._context).lock(chapter.book_id)
        await self._session.refresh(chapter)

        previous = await self._latest(chapter.id)
        why = _reason(reason, required=previous is not None)

        document = await self._source(chapter)
        parser = _parser(document)

        # Изображения читаются из того же файла, пока он под рукой, и только
        # для объектов этой главы: остальным главам они сейчас не нужны.
        async with local_copy(self._storage, document.storage_key) as path:
            source = await _parse(parser, path)
            start, end = await self._locate(chapter, source.blocks)
            placed = in_chapter(source, start, end)
            wanted = [image for item in placed for image in item.object.images]
            pictures = await asyncio.to_thread(read_pictures, path, wanted) if wanted else {}

        parsed = source.blocks[start:end]
        described = [describe(item, source.blocks, pictures) for item in placed]
        entries = [
            _entry(item, info, start, end) for item, info in zip(placed, described, strict=True)
        ]

        checksum = master_checksum([(block.kind, block.text) for block in parsed], entries)
        if previous is not None and checksum == previous.checksum:
            raise ConflictError("Текст главы не изменился — новая версия мастера не нужна")

        known = await self._active_blocks(chapter.id) if previous is not None else []
        steps = reconcile(
            [
                Existing(id=block.id, source_hash=block.source_hash, source_text=block.source_text)
                for block in known
            ],
            parsed,
        )

        known_objects = await self._objects_of(previous) if previous is not None else []
        object_steps = match(
            [
                Existing(
                    id=item.id, source_hash=object_hash(item.type, item.checksum), source_text=None
                )
                for item in known_objects
            ],
            [
                Fresh(source_hash=object_hash(info.type, info.checksum), source_text=None)
                for info in described
            ],
        )

        master_id = uuid.uuid4()
        allocator = CodeAllocator(self._session, self._context)
        creates = [step for step in steps if isinstance(step, Create)]
        # Номера для всех новых блоков главы — одним запросом, подряд.
        numbers = iter(await allocator.reserve(CodeKind.BLOCK, chapter.id, len(creates)))

        ordered: list[Block | None] = [None] * len(parsed)
        fresh: list[Block] = []
        retired = 0

        for step in steps:
            if isinstance(step, Keep):
                ordered[step.parsed] = known[step.existing]
            elif isinstance(step, Retire):
                known[step.existing].active = False
                retired += 1
            else:
                block = self._block(chapter, master_id, parsed[step.parsed], step, next(numbers))
                ordered[step.parsed] = block
                fresh.append(block)

        final = [block for block in ordered if block is not None]

        for ordinal, block in enumerate(final, start=1):
            block.ordinal = ordinal
            block.active = True

        objects, fresh_objects, retired_objects = await self._place_objects(
            chapter, master_id, described, known_objects, object_steps, allocator
        )

        # Состояние объекта в текущей версии — как место у блока: подпись и
        # номер берутся из этой версии.
        for item, entry, info in zip(objects, entries, described, strict=True):
            item.active = True
            item.caption_block_id = final[entry.caption].id if entry.caption is not None else None
            item.label = info.label

        # Версия пишется один раз и сразу окончательной: идентификаторы
        # блоков и объектов заданы явно, и списки версии с её суммой
        # известны до первой записи.
        master = ChapterMaster(
            id=master_id,
            organization_id=self.organization_id,
            chapter_id=chapter.id,
            version=(previous.version + 1) if previous is not None else 1,
            supersedes_id=previous.id if previous is not None else None,
            reason=why,
            source_document_id=document.id,
            parser_version=PARSER_VERSION,
            boundary_version=chapter.boundary_version,
            source_start=start,
            source_end=end,
            block_ids=[str(block.id) for block in final],
            objects=[
                {
                    "id": str(item.id),
                    "at": entry.at,
                    "blocks": [str(final[index].id) for index in entry.content],
                    "caption": str(final[entry.caption].id) if entry.caption is not None else None,
                    "label": info.label,
                }
                for item, entry, info in zip(objects, entries, described, strict=True)
            ],
            checksum=checksum,
            created_by_id=self._context.user.id,
        )

        await self._store_pictures(fresh_objects, pictures)

        # Запись по шагам и именно в этом порядке: версия, её блоки, их
        # части, объекты. Связей между моделями нет — только внешние
        # ключи, — и при общей фиксации порядок вставки в разные таблицы не
        # определён: блоки ушли бы в базу раньше версии, на которую
        # ссылаются. Так и случилось на живых данных, хотя тесты
        # проходили, — по везению.
        self._session.add(master)
        await self._session.flush()
        self._session.add_all(fresh)
        await self._session.flush()
        self._session.add_all(part for block in fresh for part in self._chunks(block))
        self._session.add_all(fresh_objects)
        await self._session.flush()
        created = len(fresh)

        references = await ObjectReferenceService(self._session, self._context).refresh(book.id)

        # Границы главы в новом разборе могли сдвинуться — исправленный
        # разборщик добавил блок раньше неё. Это те же границы в других
        # номерах, а не новые границы: версия границ не растёт.
        if (start, end) != (chapter.source_start, chapter.source_end):
            chapter.source_start, chapter.source_end = start, end
            chapter.sections = [
                section.as_json()
                for section in sections_of(source.blocks)
                if start <= section.start < end
            ]
        chapter.parser_version = PARSER_VERSION

        AuditService(self._session, self._context).record(
            kind="master.created",
            subject_type="chapter_master",
            subject_id=master.id,
            payload={
                "book_id": str(book.id),
                "chapter_id": str(chapter.id),
                "chapter_code": chapter.code,
                "version": master.version,
                "reason": why,
                "blocks": len(final),
                "created": created,
                "retired": retired,
                "objects": len(objects),
                "objects_created": len(fresh_objects),
                "objects_retired": retired_objects,
                "references": references,
                "checksum": master.checksum,
                "parser_version": PARSER_VERSION,
            },
        )

        await self._session.commit()
        await self._session.refresh(master)

        return master

    async def approve(self, master_id: uuid.UUID) -> ChapterMaster:
        """Подтвердить, что мастер извлечён верно.

        Утверждается только текущая версия: утверждать заменённую незачем —
        по ней уже не будут переводить.
        """
        self._context.require(*MANAGING_ROLES)

        master = await self.get(master_id)
        latest = await self._latest(master.chapter_id)

        if latest is None or latest.id != master.id:
            raise ConflictError("Утверждается только текущая версия мастера")

        if master.approved_at is not None:
            return master

        master.approved_by_id = self._context.user.id
        master.approved_at = datetime.now(UTC)

        AuditService(self._session, self._context).record(
            kind="master.approved",
            subject_type="chapter_master",
            subject_id=master.id,
            payload={
                "chapter_id": str(master.chapter_id),
                "version": master.version,
                "checksum": master.checksum,
                "decided_by": "user",
            },
        )

        await self._session.commit()
        await self._session.refresh(master)

        return master

    async def blocks(self, master_id: uuid.UUID, *, limit: int, offset: int) -> BlockPage:
        """Блоки версии мастера в её порядке — страница из общего числа.

        Порядок берётся из списка версии, а не из места блока: место — это
        порядок в текущей версии, а прежняя версия обязана показываться
        такой, какой была.
        """
        master = await self.get(master_id)
        window = [uuid.UUID(value) for value in master.block_ids[offset : offset + limit]]

        found = {
            block.id: block
            for block in await self._session.scalars(self.scoped(Block).where(Block.id.in_(window)))
        }

        return BlockPage(total=len(master.block_ids), items=[found[item] for item in window])

    async def chapter_of(self, master: ChapterMaster) -> Chapter:
        return await self._chapter(master.chapter_id)

    async def parents(self, blocks: list[Block]) -> dict[uuid.UUID, Block]:
        """Блоки, из которых получились данные, — чтобы показать их коды."""
        wanted = {block.parent_block_id for block in blocks if block.parent_block_id is not None}

        if not wanted:
            return {}

        return {
            parent.id: parent
            for parent in await self._session.scalars(
                self.scoped(Block).where(Block.id.in_(wanted))
            )
        }

    async def chunks(self, block_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Сколько частей у каждого блока — для экрана, без самих частей."""
        rows = await self._session.execute(
            select(SegmentChunk.block_id, func.count())
            .where(
                SegmentChunk.organization_id == self.organization_id,
                SegmentChunk.block_id.in_(block_ids),
            )
            .group_by(SegmentChunk.block_id)
        )

        return {block_id: count for block_id, count in rows.tuples()}

    async def find(self, code: str, *, book_id: uuid.UUID | None = None) -> FoundBlock:
        """Блок по коду — в книге (`CH03-B0042`) или в пространстве (`BK01-CH03-B0042`).

        Находится и выведенный из действия блок: на него ссылаются прежние
        версии мастера и замечания, и «не найдено» было бы неправдой.
        """
        match = _BLOCK_CODE.match(code.strip())

        if match is None:
            raise InvalidInputError("Код блока выглядит так: CH03-B0042 или BK01-CH03-B0042")

        book = await self._book(book_id, match.group("book"))
        chapter = await self._session.scalar(
            self.scoped(Chapter).where(
                Chapter.book_id == book.id, Chapter.number == int(match.group("chapter"))
            )
        )

        block = (
            await self._session.scalar(
                self.scoped(Block).where(
                    Block.chapter_id == chapter.id, Block.number == int(match.group("block"))
                )
            )
            if chapter is not None
            else None
        )

        if chapter is None or block is None:
            raise NotFoundError(f"Блок {code.strip().upper()} не найден")

        latest = await self._latest(chapter.id)
        position = (
            latest.block_ids.index(str(block.id))
            if latest is not None and str(block.id) in latest.block_ids
            else None
        )

        return FoundBlock(book=book, chapter=chapter, block=block, position=position)

    async def _book(self, book_id: uuid.UUID | None, code_number: str | None) -> BookEdition:
        if book_id is not None:
            return await BookService(self._session, self._context).get(book_id)

        if code_number is None:
            raise InvalidInputError("Вне книги код блока нужен целиком: BK01-CH03-B0042")

        book = await self._session.scalar(
            self.scoped(BookEdition).where(BookEdition.number == int(code_number))
        )

        if book is None:
            raise NotFoundError(f"Книга BK{int(code_number):02d} не найдена")

        return book

    def _block(
        self,
        chapter: Chapter,
        master_id: uuid.UUID,
        parsed: ParsedBlock,
        step: Create,
        number: int,
    ) -> Block:
        """Новый блок версии — ещё не записанный: порядок записи задаёт `extract`."""
        return Block(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            chapter_id=chapter.id,
            master_id=master_id,
            parent_block_id=step.parent,
            number=number,
            kind=parsed.kind,
            ordinal=0,
            source_text=parsed.text,
            source_location=dict(parsed.location),
            source_hash=block_hash(parsed.kind, parsed.text),
            active=True,
        )

    def _chunks(self, block: Block) -> list[SegmentChunk]:
        """Части блока для модели; их склейка — ровно его текст."""
        settings = get_settings()
        parts = chunk(
            block.source_text,
            block.kind,
            target_chars=settings.segment_target_chars,
            hard_limit_chars=settings.segment_hard_limit_chars,
        )

        return [
            SegmentChunk(
                organization_id=self.organization_id,
                block_id=block.id,
                chunk_index=index,
                source_text=part,
                token_estimate=estimate_tokens(part, SOURCE_CHARS_PER_TOKEN),
            )
            for index, part in enumerate(parts)
        ]

    async def _locate(self, chapter: Chapter, blocks: list[ParsedBlock]) -> tuple[int, int]:
        following = await self._session.scalar(
            self.scoped(Chapter).where(
                Chapter.book_id == chapter.book_id, Chapter.ordinal == chapter.ordinal + 1
            )
        )

        try:
            return locate(
                blocks,
                first_section=chapter.sections[0],
                previous_start=chapter.source_start,
                following_section=following.sections[0] if following is not None else None,
                following_start=following.source_start if following is not None else None,
            )
        except AnchorNotFoundError as error:
            raise ConflictError(
                f"{error}. Файл разбирается иначе, чем при разметке глав, — "
                "границы главы нужно проверить заново"
            ) from error

    async def _place_objects(
        self,
        chapter: Chapter,
        master_id: uuid.UUID,
        described: list[Described],
        known: list[BookObject],
        steps: list[Step],
        allocator: CodeAllocator,
    ) -> tuple[list[BookObject], list[BookObject], int]:
        """Объекты новой версии по порядку, из них новые, и сколько выведено.

        Номера — у каждого вида свои, и каждый вид получает отрезок одним
        запросом: рисунки нумеруются отдельно от таблиц, как и в книге.
        """
        needed = Counter(described[step.parsed].type for step in steps if isinstance(step, Create))
        numbers = {
            kind: iter(await allocator.reserve(CodeKind[kind.name], chapter.id, count))
            for kind, count in needed.items()
        }

        ordered: list[BookObject | None] = [None] * len(described)
        fresh: list[BookObject] = []
        retired = 0

        for step in steps:
            if isinstance(step, Keep):
                ordered[step.parsed] = known[step.existing]
            elif isinstance(step, Retire):
                known[step.existing].active = False
                retired += 1
            else:
                info = described[step.parsed]
                item = BookObject(
                    id=uuid.uuid4(),
                    organization_id=self.organization_id,
                    chapter_id=chapter.id,
                    master_id=master_id,
                    parent_object_id=step.parent,
                    type=info.type,
                    number=next(numbers[info.type]),
                    source_location=info.location,
                    payload=info.payload,
                    checksum=info.checksum,
                    active=True,
                )
                ordered[step.parsed] = item
                fresh.append(item)

        return [item for item in ordered if item is not None], fresh, retired

    async def _store_pictures(
        self, objects: list[BookObject], pictures: dict[ImageSource, Picture]
    ) -> None:
        """Положить изображения новых рисунков в хранилище — до записи в базу.

        Ключ — по содержимому, поэтому повтор безвреден: та же картинка
        ляжет тем же файлом. Откатится транзакция — файл останется
        неиспользованным, но ни на что неверное ссылаться не будет.
        """
        wanted = {
            entry["sha256"]
            for item in objects
            if item.type is ObjectType.FIGURE
            for entry in item.payload.get("images", [])
            if entry.get("sha256")
        }

        for picture in {picture.sha256: picture for picture in pictures.values()}.values():
            if picture.sha256 not in wanted:
                continue

            descriptor, name = tempfile.mkstemp(prefix="booktranslate-figure-")
            path = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    await asyncio.to_thread(handle.write, picture.data)
                await self._storage.put(picture_key(self.organization_id, picture.sha256), path)
            finally:
                path.unlink(missing_ok=True)

    async def _objects_of(self, master: ChapterMaster) -> list[BookObject]:
        """Объекты версии мастера в её порядке."""
        ids = [uuid.UUID(entry["id"]) for entry in master.objects]

        if not ids:
            return []

        found = {
            item.id: item
            for item in await self._session.scalars(
                self.scoped(BookObject).where(BookObject.id.in_(ids))
            )
        }

        return [found[item] for item in ids]

    async def _source(self, chapter: Chapter) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == chapter.source_document_id)
        )

        if document is None:
            raise NotFoundError("Файл, по которому размечена глава, не найден")

        return document

    async def _active_blocks(self, chapter_id: uuid.UUID) -> list[Block]:
        return list(
            await self._session.scalars(
                self.scoped(Block)
                .where(Block.chapter_id == chapter_id, Block.active.is_(True))
                .order_by(Block.ordinal)
            )
        )

    async def _latest(self, chapter_id: uuid.UUID) -> ChapterMaster | None:
        master: ChapterMaster | None = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )

        return master

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))

        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter


def _parser(document: Document) -> DocumentParser:
    parser = parser_for(document.source_format)

    if parser is None:
        raise InvalidInputError(f"Формат {document.source_format.value} пока не разбирается")

    return parser


async def _parse(parser: DocumentParser, path: Path) -> ParsedSource:
    try:
        return await asyncio.to_thread(lambda: collect(parser.parse(path)))
    except ParsingError as error:
        raise InvalidInputError(str(error)) from error


def _entry(placed: PlacedObject, info: Described, start: int, end: int) -> PlacedEntry:
    """Объект в координатах главы: номера блоков от её начала.

    Место — сколько блоков главы стоит перед объектом. Рисунок, отнесённый
    к главе по соседнему блоку, может стоять на её краю, но не за ним.
    """
    return PlacedEntry(
        type=info.type,
        checksum=info.checksum,
        at=min(max(placed.at - start, 0), end - start),
        content=tuple(index - start for index in placed.content if start <= index < end),
        caption=(
            placed.caption - start
            if placed.caption is not None and start <= placed.caption < end
            else None
        ),
    )


def _reason(value: str | None, *, required: bool) -> str | None:
    """Причина новой версии — одной строкой, в разумных пределах."""
    clean = " ".join((value or "").split())

    if not clean:
        if required:
            raise InvalidInputError(
                "Новая версия мастера без причины невозможна: опишите, что не так с прежней"
            )
        return None

    if len(clean) < REASON_MIN:
        raise InvalidInputError(f"Причина — хотя бы {REASON_MIN} знаков: что именно не так")

    if len(clean) > REASON_MAX:
        raise InvalidInputError(f"Причина — не длиннее {REASON_MAX} знаков")

    return clean
