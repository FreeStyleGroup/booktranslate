"""Смета главы: что в ней и во что обойдётся её перевод.

Отвечает на вопросы, которые задают до того, как платить: сколько в главе текста,
из чего он состоит, сколько в нём повторов, что уже закрыто готовыми переводами и
сколько остаётся оплачивать.

Считается по запросу, а не хранится. Причина та же, по которой готовность не лежит
колонкой: числа меняются после каждого прогона, и сохранённые однажды они разойдутся
с действительностью — молча и незаметно, потому что выглядеть будут правдоподобно.

Повторы и совпадения считаются только среди непереведённого и теми же правилами,
что у самого прогона (`translation_runner`): разойдись они — смета обещала бы
экономию, которой перевод потом не найдёт.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from app.models.block import Block
from app.models.book import BookEdition
from app.models.chapter import Chapter
from app.models.translation import RevisionOrigin, TranslationRevision, TranslationRun
from app.services.base import TenantService
from app.services.errors import NotFoundError
from app.services.memory import TranslationMemory, fingerprint
from app.services.pricing import Forecast, forecast
from app.services.terminology_gate import TerminologyGate
from app.services.translation_runner import is_protected


@dataclass(slots=True)
class ChapterEstimate:
    """Состав главы и смета на её перевод."""

    blocks: int = 0
    characters: int = 0
    words: int = 0
    longest_block_chars: int = 0

    # Из чего глава состоит: заголовки, абзацы, ячейки таблиц, листинги.
    by_kind: dict[str, int] = field(default_factory=dict)

    untranslated: int = 0
    # Листинги и то, в чём нет букв: переносятся как есть и ничего не стоят.
    protected: int = 0
    # Различных текстов среди остального и сколько повторов.
    unique_untranslated: int = 0
    repeated: int = 0
    # Различные тексты, у которых уже есть готовый перевод.
    book_matches: int = 0
    memory_matches: int = 0

    # За что предстоит заплатить.
    billable_texts: int = 0
    billable_characters: int = 0

    estimate: Forecast | None = None


class EstimateService(TenantService):
    async def build(
        self, chapter_id: uuid.UUID, *, model: str, context_segments: int
    ) -> ChapterEstimate:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        book = await self._session.scalar(
            self.scoped(BookEdition).where(BookEdition.id == chapter.book_id)
        )
        if book is None:
            raise NotFoundError("Книга не найдена")

        blocks = list(
            await self._session.scalars(
                self.scoped(Block).where(Block.chapter_id == chapter.id, Block.active.is_(True))
            )
        )
        estimate = ChapterEstimate(
            blocks=len(blocks),
            characters=sum(len(block.source_text) for block in blocks),
            words=sum(len(block.source_text.split()) for block in blocks),
            longest_block_chars=max((len(block.source_text) for block in blocks), default=0),
        )

        for block in blocks:
            kind = block.kind.value
            estimate.by_kind[kind] = estimate.by_kind.get(kind, 0) + 1

        pending = [block for block in blocks if block.current_revision_id is None]
        estimate.untranslated = len(pending)

        translatable = [
            block for block in pending if not is_protected(block.kind, block.source_text)
        ]
        estimate.protected = len(pending) - len(translatable)

        # Как у прогона: одинаковые блоки — один текст.
        unique: dict[str, Block] = {}
        for block in translatable:
            unique.setdefault(block.source_hash, block)

        estimate.unique_untranslated = len(unique)
        estimate.repeated = len(translatable) - len(unique)

        version = await TerminologyGate(self._session, self._context).effective(book.id, chapter.id)
        in_book = await self._in_book(
            book.id, set(unique), version.id if version is not None else None
        )
        rest = {digest: block for digest, block in unique.items() if digest not in in_book}
        estimate.book_matches = len(in_book)

        known = await TranslationMemory(self._session, self._context).known(
            {fingerprint(block.source_text) for block in rest.values()},
            source_language=book.source_language,
            target_language=book.target_language,
        )
        billable = [block for block in rest.values() if fingerprint(block.source_text) not in known]
        estimate.memory_matches = len(rest) - len(billable)
        estimate.billable_texts = len(billable)
        estimate.billable_characters = sum(len(block.source_text) for block in billable)

        if estimate.billable_characters > 0:
            estimate.estimate = forecast(
                model,
                characters=estimate.billable_characters,
                context_segments=context_segments,
            )

        return estimate

    async def _in_book(
        self, book_id: uuid.UUID, hashes: set[str], version_id: uuid.UUID | None
    ) -> set[str]:
        """Какие тексты уже переведены в этой книге по той же версии глоссария."""
        if not hashes:
            return set()

        rows = await self._session.scalars(
            select(Block.source_hash)
            .join(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .join(TranslationRun, TranslationRun.id == TranslationRevision.run_id)
            .where(
                Block.organization_id == self.organization_id,
                Block.source_hash.in_(hashes),
                Chapter.book_id == book_id,
                TranslationRevision.origin != RevisionOrigin.COPY,
                TranslationRun.glossary_version_id.is_not_distinct_from(version_id),
            )
        )

        return set(rows)
