"""Исполнение прогона перевода: то, что делает рабочий процесс.

Цель та же, что и была: перевод, который можно отдать в печать, — а значит,
к моменту, когда блок уходит в модель, всё, что можно решить заранее, решено.
Меняется только то, куда кладётся результат: в новую неизменяемую редакцию, а
не поверх прежнего текста.

Порядок для каждой порции блоков:

1. **Защищённое не уходит в модель.** Листинг и то, в чём нет ни одной буквы,
   переносятся знак в знак. Ячейка с числом и строка кода переводу не подлежат.
2. **Готовый перевод того же текста.** Сперва из этой же книги — и только
   сделанный по той же версии глоссария, — затем из памяти переводов. Заново
   перевести нельзя лишь первое употребление термина: там текст особый.
3. **Одинаковые блоки переводятся один раз.** Повторяющееся предупреждение
   обязано звучать в книге одинаково.
4. **Части блока идут в одной пачке.** Каждая несёт свой код, а защищённое
   внутри фразы заменено заменителем. Ответ, потерявший код или заменитель,
   отвергается: одна повторная попытка, потом блок остаётся без редакции и
   причина записывается в прогон.

Перевод заново работает иначе: память и повторы он не спрашивает — человек
просит именно новый вариант, — и текущую редакцию не трогает.

🔥 Сделанное фиксируется после каждой пачки, а повтор пачки после сбоя не
создаст второй редакции: на пару «прогон — блок» стоит ограничение в базе.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.block import Block, BlockKind, SegmentChunk
from app.models.book import BookEdition
from app.models.chapter import Chapter
from app.models.master import ChapterMaster
from app.models.memory import FirstUseRule
from app.models.translation import (
    RevisionOrigin,
    RevisionStage,
    RunKind,
    TranslationRevision,
    TranslationRun,
)
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, NotFoundError
from app.services.glossary import Glossary, GlossaryService
from app.services.memory import TranslationMemory, fingerprint
from app.services.protection import (
    Masked,
    TokenMismatchError,
    find_spans,
    join_pieces,
    mask,
    stored_spans,
    unmask,
)
from app.services.providers import (
    Neighbourhood,
    ProviderError,
    TranslationProvider,
    TranslationRequest,
    Usage,
)

_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def is_protected(kind: BlockKind, text: str) -> bool:
    """Блок переносится как есть: листинг и всё, в чём нет ни одной буквы."""
    return kind is BlockKind.CODE or _LETTERS.search(text) is None


@dataclass(frozen=True, slots=True)
class Advance:
    """Чем кончилась порция: сколько блоков закрыто и сколько осталось."""

    processed: int
    remaining: int


@dataclass(frozen=True, slots=True)
class _Piece:
    """Часть блока, ушедшая в модель."""

    key: str
    source: str
    masked: Masked
    request: TranslationRequest


@dataclass(slots=True)
class _Group:
    """Одинаковые блоки: переводятся один раз, редакцию получает каждый."""

    blocks: list[Block]
    pieces: list[_Piece] = field(default_factory=list)


@dataclass(slots=True)
class _Answer:
    items: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True, slots=True)
class _Ready:
    """Готовая к записи редакция блока."""

    block: Block
    text: str
    origin: RevisionOrigin
    memory_unit_id: uuid.UUID | None = None
    copied_from_id: uuid.UUID | None = None


class TranslationRunner(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, provider: TranslationProvider
    ) -> None:
        super().__init__(session, context)
        self._provider = provider

    async def advance(self, run_id: uuid.UUID, *, limit: int) -> Advance:
        """Перевести очередную порцию блоков прогона.

        Текст главы сверяется в начале каждой порции: прогон по версии мастера,
        которой больше нет, переводил бы то, чего в книге уже не будет.
        """
        run = await self._session.scalar(
            self.scoped(TranslationRun).where(TranslationRun.id == run_id)
        )
        if run is None:
            raise NotFoundError("Прогон перевода не найден")

        await self._require_current_master(run)

        book = await self._session.scalar(
            self.scoped(BookEdition).where(BookEdition.id == run.book_id)
        )
        if book is None:
            raise NotFoundError("Книга не найдена")

        order = await self._active_blocks(run.chapter_id)
        blocks = self._next(run, order, await self._done(run), limit)

        if not blocks:
            return Advance(processed=0, remaining=0)

        glossary = await self._glossary(run, book)
        first_use = first_uses(glossary, order)

        copies = [block for block in blocks if is_protected(block.kind, block.source_text)]
        rest = [block for block in blocks if not is_protected(block.kind, block.source_text)]

        await self._store(
            run, [_Ready(block, block.source_text, RevisionOrigin.COPY) for block in copies]
        )

        if run.kind is RunKind.DRAFT:
            rest = await self._reuse(run, book, rest, first_use)

        groups = await self._groups(run, rest, order, glossary, book, first_use)

        for batch in _packs(groups, get_settings().translation_batch_size):
            await self._translate(run, batch)

        # Отвергнутые тоже считаются: для этого прогона они закрыты.
        return Advance(
            processed=len(blocks),
            remaining=len(self._next(run, order, await self._done(run), limit=None)),
        )

    async def _require_current_master(self, run: TranslationRun) -> None:
        latest = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == run.chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )

        if latest is None or latest.id != run.master_id:
            raise ConflictError(
                "У главы появилась новая версия мастера: прогон остановлен, запустите перевод "
                "заново"
            )

    async def _active_blocks(self, chapter_id: uuid.UUID) -> list[Block]:
        return list(
            await self._session.scalars(
                self.scoped(Block)
                .where(Block.chapter_id == chapter_id, Block.active.is_(True))
                .order_by(Block.ordinal)
            )
        )

    async def _done(self, run: TranslationRun) -> set[uuid.UUID]:
        """Блоки, которые этот прогон уже закрыл: редакцией или отказом."""
        written = await self._session.scalars(
            select(TranslationRevision.block_id).where(TranslationRevision.run_id == run.id)
        )

        return {*written, *(uuid.UUID(item["block_id"]) for item in run.rejections)}

    @staticmethod
    def _next(
        run: TranslationRun, order: Sequence[Block], done: set[uuid.UUID], limit: int | None
    ) -> list[Block]:
        if run.kind is RunKind.DRAFT:
            wanted = [
                block
                for block in order
                if block.current_revision_id is None and block.id not in done
            ]
        else:
            chosen = {uuid.UUID(item["block_id"]) for item in run.selection}
            wanted = [block for block in order if block.id in chosen and block.id not in done]

        return wanted if limit is None else wanted[:limit]

    async def _glossary(self, run: TranslationRun, book: BookEdition) -> Glossary:
        service = GlossaryService(self._session, self._context)

        if run.glossary_version_id is not None:
            return await service.load_version(run.glossary_version_id)

        # Обход гейта при отсутствии версии: рабочий словарь как есть.
        return await service.load(
            project_id=book.project_id,
            source_language=book.source_language,
            target_language=book.target_language,
        )

    async def _reuse(
        self,
        run: TranslationRun,
        book: BookEdition,
        blocks: list[Block],
        first_use: dict[uuid.UUID, tuple[str, ...]],
    ) -> list[Block]:
        """Закрыть то, чему уже есть готовый перевод, и вернуть остальное.

        Перевод из книги важнее памяти: память общая для пространства, а книга
        обязана быть согласована сама с собой. Чужая версия глоссария не
        годится: термины в том тексте могут быть другими.
        """
        reusable = [block for block in blocks if block.id not in first_use]
        if not reusable:
            return blocks

        known = await self._same_text_in_book(run, book, {block.source_hash for block in reusable})
        units = await TranslationMemory(self._session, self._context).lookup(
            [block.source_text for block in reusable if block.source_hash not in known],
            source_language=book.source_language,
            target_language=book.target_language,
        )

        ready: list[_Ready] = []
        used_units: set[uuid.UUID] = set()

        for block in reusable:
            revision = known.get(block.source_hash)
            if revision is not None:
                ready.append(
                    _Ready(block, revision.text, RevisionOrigin.MEMORY, copied_from_id=revision.id)
                )
                continue

            unit = units.get(fingerprint(block.source_text))
            if unit is not None:
                ready.append(
                    _Ready(block, unit.target_text, RevisionOrigin.MEMORY, memory_unit_id=unit.id)
                )
                used_units.add(unit.id)

        await TranslationMemory(self._session, self._context).count_hits(list(used_units))
        await self._store(run, ready)

        closed = {item.block.id for item in ready}

        return [block for block in blocks if block.id not in closed]

    async def _same_text_in_book(
        self, run: TranslationRun, book: BookEdition, hashes: set[str]
    ) -> dict[str, TranslationRevision]:
        if not hashes:
            return {}

        rows = await self._session.execute(
            select(Block.source_hash, TranslationRevision)
            .join(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .join(TranslationRun, TranslationRun.id == TranslationRevision.run_id)
            .where(
                Block.organization_id == self.organization_id,
                Block.source_hash.in_(hashes),
                Chapter.book_id == book.id,
                TranslationRevision.origin != RevisionOrigin.COPY,
                TranslationRun.glossary_version_id.is_not_distinct_from(run.glossary_version_id),
            )
            .order_by(TranslationRevision.created_at)
        )

        return {digest: revision for digest, revision in rows.all()}

    async def _groups(
        self,
        run: TranslationRun,
        blocks: list[Block],
        order: Sequence[Block],
        glossary: Glossary,
        book: BookEdition,
        first_use: dict[uuid.UUID, tuple[str, ...]],
    ) -> list[_Group]:
        """Собрать одинаковые блоки и запросы к модели.

        Первое употребление термина в группу не объединяется: там текст особый,
        и переносить его на сороковой такой же абзац нельзя. Перевод заново
        повторов не ищет вовсе: вариант просят для конкретного блока.
        """
        if not blocks:
            return []

        chunks = await self._chunks([block.id for block in blocks])
        size = get_settings().translation_context_segments
        context = _neighbourhoods(order, size)
        chapter = await self._session.scalar(
            self.scoped(Chapter).where(Chapter.id == run.chapter_id)
        )
        prefix = (chapter.code if chapter is not None else None) or "CH"

        groups: dict[object, _Group] = {}

        for block in blocks:
            key: object = (
                block.id
                if run.kind is RunKind.RETRANSLATE or block.id in first_use
                else block.source_hash
            )
            group = groups.get(key)

            if group is not None:
                group.blocks.append(block)
                continue

            groups[key] = _Group(
                blocks=[block],
                pieces=_pieces(
                    block,
                    chunks.get(block.id, []),
                    code=f"{prefix}-{block.code}",
                    glossary=glossary,
                    book=book,
                    context=context[block.id],
                    context_size=size,
                    first_use=first_use.get(block.id, ()),
                ),
            )

        return list(groups.values())

    async def _chunks(self, block_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[SegmentChunk]]:
        rows = await self._session.scalars(
            self.scoped(SegmentChunk)
            .where(SegmentChunk.block_id.in_(block_ids))
            .order_by(SegmentChunk.block_id, SegmentChunk.chunk_index)
        )
        found: dict[uuid.UUID, list[SegmentChunk]] = {}

        for row in rows:
            found.setdefault(row.block_id, []).append(row)

        return found

    async def _translate(self, run: TranslationRun, batch: list[_Group]) -> None:
        """Одна пачка: запрос, проверка заменителей, запись редакций одной фиксацией."""
        pieces = [piece for group in batch for piece in group.pieces]
        answer = await self._ask([piece.request for piece in pieces])

        # Заменитель потерян — заход ещё один, но уже этой частью одной: в
        # одиночку модель ошибается заметно реже, а просить всю пачку заново
        # значит платить за то, что уже получено верно.
        checked: dict[str, str] = {}
        broken: list[_Piece] = []

        for piece in pieces:
            raw = answer.items.get(piece.key)
            if raw is None:
                continue

            try:
                checked[piece.key] = _restored(raw, piece)
            except (TokenMismatchError, _EmptyAnswerError):
                broken.append(piece)

        for piece in broken:
            second = await self._ask([piece.request])
            answer.usage = answer.usage + second.usage
            raw = second.items.get(piece.key)

            if raw is None:
                answer.failures[piece.key] = second.failures.get(piece.key, "модель не ответила")
                continue

            try:
                checked[piece.key] = _restored(raw, piece)
            except (TokenMismatchError, _EmptyAnswerError) as error:
                answer.failures[piece.key] = str(error)

        ready: list[_Ready] = []
        rejections: list[dict[str, str]] = []

        for group in batch:
            reason = next(
                (
                    answer.failures.get(piece.key, "модель не вернула перевод")
                    for piece in group.pieces
                    if piece.key not in checked
                ),
                None,
            )

            if reason is not None or not group.pieces:
                rejections.extend(
                    {
                        "block_id": str(block.id),
                        "code": block.code,
                        "reason": reason or "у блока нет частей для перевода",
                    }
                    for block in group.blocks
                )
                continue

            text = join_pieces(
                [piece.source for piece in group.pieces],
                [checked[piece.key] for piece in group.pieces],
            )
            ready.extend(_Ready(block, text, RevisionOrigin.MODEL) for block in group.blocks)

        run.input_tokens += answer.usage.input_tokens
        run.output_tokens += answer.usage.output_tokens
        run.cached_input_tokens += answer.usage.cached_input_tokens
        run.cache_write_tokens += answer.usage.cache_write_tokens

        if rejections:
            run.rejections = [*run.rejections, *rejections]

        await self._store(run, ready)

    async def _ask(self, requests: list[TranslationRequest]) -> _Answer:
        """Спросить модель; не удавшуюся пачку — половинами.

        Отказ по одному абзацу не должен стоить главы: пачка делится, пока виновный
        не останется один, и без редакции остаётся только он. Сбой сети сюда не
        попадает — это не отказ, и повторять его будет очередь целиком.
        """
        keys = [request.key for request in requests]

        try:
            batch = await self._provider.translate(requests)
        except ProviderError as error:
            return await self._split(requests, reason=str(error), spent=error.spent)

        if set(batch.items) != set(keys):
            return await self._split(
                requests,
                reason=_mismatch(keys, batch.items),
                spent=batch.usage,
            )

        return _Answer(items=dict(batch.items), usage=batch.usage)

    async def _split(
        self, requests: list[TranslationRequest], *, reason: str, spent: Usage
    ) -> _Answer:
        if len(requests) == 1:
            return _Answer(failures={requests[0].key: reason}, usage=spent)

        middle = len(requests) // 2
        head = await self._ask(requests[:middle])
        tail = await self._ask(requests[middle:])

        return _Answer(
            items={**head.items, **tail.items},
            failures={**head.failures, **tail.failures},
            usage=spent + head.usage + tail.usage,
        )

    async def _store(self, run: TranslationRun, ready: list[_Ready]) -> None:
        """Записать редакции и зафиксировать.

        Сначала редакции, потом указатели на них: связи ORM между ними нет, и
        порядок вставки при общей фиксации не определён.
        """
        numbers = await self._next_numbers([item.block.id for item in ready])
        bases = {uuid.UUID(item["block_id"]): item["base_revision_id"] for item in run.selection}
        revisions = []

        for item in ready:
            base = bases.get(item.block.id)
            revisions.append(
                TranslationRevision(
                    id=uuid.uuid4(),
                    organization_id=self.organization_id,
                    block_id=item.block.id,
                    revision_no=numbers[item.block.id],
                    stage=RevisionStage.DRAFT,
                    origin=item.origin,
                    text=item.text,
                    run_id=run.id,
                    supersedes_id=uuid.UUID(base) if base else None,
                    memory_unit_id=item.memory_unit_id,
                    copied_from_id=item.copied_from_id,
                    created_by_id=run.requested_by_id,
                )
            )

        self._session.add_all(revisions)
        await self._session.flush()

        # Перевод заново текущую редакцию не меняет: новый текст лежит вариантом,
        # пока его не примут.
        if run.kind is RunKind.DRAFT:
            for item, revision in zip(ready, revisions, strict=True):
                item.block.current_revision_id = revision.id

        for item in ready:
            if item.origin is RevisionOrigin.MODEL:
                run.from_model += 1
            elif item.origin is RevisionOrigin.MEMORY:
                run.from_memory += 1
            else:
                run.copied += 1

        await self._session.commit()

    async def _next_numbers(self, block_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not block_ids:
            return {}

        rows = await self._session.execute(
            select(TranslationRevision.block_id, func.max(TranslationRevision.revision_no))
            .where(TranslationRevision.block_id.in_(block_ids))
            .group_by(TranslationRevision.block_id)
        )
        latest = {block_id: int(number) for block_id, number in rows.all()}

        return {block_id: latest.get(block_id, 0) + 1 for block_id in block_ids}


class _EmptyAnswerError(Exception):
    """Модель вернула пустой перевод непустого текста."""


def _restored(raw: str, piece: _Piece) -> str:
    if not raw.strip():
        raise _EmptyAnswerError("модель вернула пустой перевод")

    return unmask(raw, piece.masked)


def _mismatch(keys: Iterable[str], items: dict[str, str]) -> str:
    expected = set(keys)
    extra = sorted(set(items) - expected)
    lost = sorted(expected - set(items))

    parts = []
    if lost:
        parts.append("нет перевода для: " + ", ".join(lost))
    if extra:
        parts.append("лишние коды: " + ", ".join(extra))

    return "Ответ модели не совпал с запросом — " + "; ".join(parts)


def _packs(groups: list[_Group], size: int) -> Iterable[list[_Group]]:
    """Разложить группы на пачки. Части одного блока не разрываются."""
    pack: list[_Group] = []
    pieces = 0

    for group in groups:
        if pack and pieces + len(group.pieces) > size:
            yield pack
            pack, pieces = [], 0

        pack.append(group)
        pieces += len(group.pieces)

    if pack:
        yield pack


def first_uses(glossary: Glossary, order: Sequence[Block]) -> dict[uuid.UUID, tuple[str, ...]]:
    """В каких блоках термин с правилом встречается в главе впервые.

    Область — глава, а не книга: главы переводятся в любом порядке и читаются
    порознь, а результат не должен зависеть от того, какую взяли раньше.
    """
    ruled = Glossary(
        [term for term in glossary.terms if term.first_use_rule is not FirstUseRule.NONE]
    )
    if not len(ruled):
        return {}

    seen: set[str] = set()
    found: dict[uuid.UUID, tuple[str, ...]] = {}

    for block in order:
        fresh = tuple(
            term.source for term in ruled.match(block.source_text) if term.source not in seen
        )

        if fresh:
            seen.update(fresh)
            found[block.id] = fresh

    return found


def _neighbourhoods(order: Sequence[Block], size: int) -> dict[uuid.UUID, Neighbourhood]:
    """Окружение каждого блока главы.

    Вся глава, а не порция: соседом непереведённого блока может быть давно
    готовый, и без него контекст рвётся ровно на границе прошлого захода.
    """
    context: dict[uuid.UUID, Neighbourhood] = {}
    heading: str | None = None

    for index, block in enumerate(order):
        context[block.id] = Neighbourhood(
            before=tuple(item.source_text for item in order[max(0, index - size) : index]),
            after=tuple(item.source_text for item in order[index + 1 : index + 1 + size]),
            heading=heading,
        )

        # Для самого заголовка предметную область задаёт предыдущий, а не он сам.
        if block.kind is BlockKind.HEADING:
            heading = block.source_text

    return context


def _pieces(
    block: Block,
    chunks: Sequence[SegmentChunk],
    *,
    code: str,
    glossary: Glossary,
    book: BookEdition,
    context: Neighbourhood,
    context_size: int,
    first_use: tuple[str, ...],
) -> list[_Piece]:
    pieces = []
    offset = 0
    waiting = set(first_use)
    sources = [chunk.source_text for chunk in chunks]

    for index, source in enumerate(sources):
        spans = find_spans(
            source, stored_spans(block.source_location, offset=offset, length=len(source))
        )
        masked = mask(source, spans)
        terms = glossary.match(source)
        here = tuple(term.source for term in terms if term.source in waiting)
        waiting.difference_update(here)
        key = f"{code}/{index}"

        pieces.append(
            _Piece(
                key=key,
                source=source,
                masked=masked,
                request=TranslationRequest(
                    key=key,
                    source_text=masked.text.strip(),
                    source_language=book.source_language,
                    target_language=book.target_language,
                    terms=terms,
                    kind=block.kind.value,
                    # Остальные части блока — тоже соседи: длинный абзац режется
                    # по предложениям, и «он» в третьем относится ко второму.
                    context=Neighbourhood(
                        before=(
                            (*context.before, *sources[:index])[-context_size:]
                            if context_size
                            else ()
                        ),
                        after=(*sources[index + 1 :], *context.after)[:context_size],
                        heading=context.heading,
                    ),
                    first_use=here,
                ),
            )
        )
        offset += len(source)

    return pieces
