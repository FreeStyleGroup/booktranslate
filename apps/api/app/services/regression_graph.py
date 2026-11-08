"""Граф зависимостей: что могло задеть исправление блока.

Расчёт только считает и записывает: он ничего не правит. Обязательным считается то, что может
разойтись с исправлением: тот же исходный текст, употребление термина, упоминания объекта, ссылки на
раздел, подпись таблицы и рисунка. Соседние блоки показываются, но закрытие не держат: иначе правка
каждого абзаца тянула бы обязательный просмотр двух соседних.

Повтор исходного текста безопасен, только если его текст совпадал с исправленным дословно: тогда это
тот же перевод тех же слов. Если текст уже другой, значит контекст мог оказаться другим, и применить
исправление можно только после решения человека.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book_object import BookObject, ObjectReference, ObjectType
from app.models.chapter import Chapter
from app.models.issue import Issue
from app.models.master import ChapterMaster
from app.models.regression import (
    DependencyKind,
    RegressionDecision,
    RegressionItem,
    RegressionRun,
    RegressionStatus,
)
from app.models.review import ReviewCoverage, ReviewKind, ReviewRun, ReviewStatus
from app.models.translation import RevisionOrigin, RevisionStage, TranslationRevision
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.book_objects import ObjectService, PlacedObject
from app.services.context import RequestContext
from app.services.errors import NotFoundError
from app.services.glossary import Glossary, GlossaryService, term_is_used
from app.services.storage import ObjectStorage
from app.services.terminology_gate import TerminologyGate

# Потолок на один вид связи: термин из каждого абзаца не должен превращать прогон в обход книги.
# Порядок в запросах задан: при потолке в прогон должны попадать одни и те же места.
ITEM_CEILING = 200

# Причины решений автоматического режима: их читает человек в списке мест регрессии.
AUTO_PROPAGATED = "Автоматический режим: повтор того же текста получил то же исправление"
AUTO_SAME = "Автоматический режим: здесь уже тот же исправленный текст"
AUTO_DIFFERENT = (
    "Автоматический режим: перевод повтора отличается от исправленного — оставлен как есть, "
    "его проверяют свои проверки"
)
AUTO_FINAL = "Автоматический режим: здесь утверждённый текст — без человека он не перезаписывается"
AUTO_UNSEEN = (
    "Автоматический режим: связанное место человек не смотрел — его текст проверяют свои проверки"
)


async def approved_revisions(
    session: AsyncSession, organization_id: uuid.UUID, revision_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Редакции, прошедшие завершённую финальную сверку: их без решения не перезаписывают."""
    if not revision_ids:
        return set()

    rows = await session.scalars(
        select(ReviewCoverage.revision_id)
        .join(ReviewRun, ReviewRun.id == ReviewCoverage.run_id)
        .where(
            ReviewRun.organization_id == organization_id,
            ReviewRun.kind == ReviewKind.FINAL_COMPARE,
            ReviewRun.status == ReviewStatus.COMPLETED,
            ReviewCoverage.revision_id.in_(revision_ids),
        )
    )

    return {row for row in rows if row is not None}


_HEADING_LABEL = re.compile(r"^\s*(\d+(?:\.\d+)*)\b")


@dataclass(frozen=True, slots=True)
class _Found:
    kind: DependencyKind
    block_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    required: bool = True
    base_revision_id: uuid.UUID | None = None
    proposed_text: str | None = None
    safe: bool = False


class RegressionGraph(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def open_for(
        self, issue: Issue, block: Block, *, old_text: str, new_text: str, revision_id: uuid.UUID
    ) -> RegressionRun:
        """Завести прогон на это исправление; транзакцией управляет вызывающий."""
        # Замечание открыли заново и исправили той же редакцией: решения по этим местам в силе.
        earlier = await self._session.scalar(
            self.scoped(RegressionRun).where(
                RegressionRun.issue_id == issue.id, RegressionRun.fix_revision_id == revision_id
            )
        )
        if earlier is not None:
            pending = await self._session.scalar(
                select(RegressionItem.id)
                .where(
                    RegressionItem.run_id == earlier.id,
                    RegressionItem.required.is_(True),
                    RegressionItem.decision == RegressionDecision.PENDING,
                )
                .limit(1)
            )
            earlier.status = (
                RegressionStatus.OPEN if pending is not None else RegressionStatus.COMPLETED
            )

            return earlier

        book_id = await self._session.scalar(
            select(Chapter.book_id).where(Chapter.id == block.chapter_id)
        )
        if book_id is None:
            raise NotFoundError("Глава не найдена")

        found: list[_Found] = [
            *await self._repeats(book_id, block, old_text, new_text),
            *await self._term_usage(book_id, block, old_text, new_text),
            *await self._objects(block),
            *await self._cross_references(book_id, block),
            *await self._adjacent(block),
        ]

        # Одно место по одной связи — один раз, и сам исправленный блок в счёт не идёт.
        unique = {
            (item.kind, item.block_id, item.object_id): item
            for item in found
            if item.block_id != block.id
        }

        run = RegressionRun(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            issue_id=issue.id,
            fix_revision_id=revision_id,
            # Время часов: последним считается прогон последнего исправления.
            created_at=datetime.now(UTC),
            # Связей нет — и решать нечего: держать закрытие было бы нечем.
            status=(
                RegressionStatus.OPEN
                if any(item.required for item in unique.values())
                else RegressionStatus.COMPLETED
            ),
        )
        self._session.add(run)
        await self._session.flush()

        for item in unique.values():
            self._session.add(
                RegressionItem(
                    organization_id=self.organization_id,
                    run_id=run.id,
                    kind=item.kind,
                    block_id=item.block_id,
                    object_id=item.object_id,
                    required=item.required,
                    base_revision_id=item.base_revision_id,
                    proposed_text=item.proposed_text,
                    safe=item.safe,
                )
            )

        return run

    async def settle_automatically(self, run: RegressionRun) -> None:
        """Автоматический режим решает места сам; транзакцией управляет вызывающий.

        Повтор с дословно тем же прежним текстом получает то же исправление: это тот же перевод тех
        же слов. Остальные места отмечаются «не затронуто» с причиной — человек их не смотрел, и
        запись говорит об этом прямо. Кандидат в финальный текст и утверждённая редакция не
        перезаписываются.
        """
        await self._session.flush()

        items = list(
            await self._session.scalars(
                self.scoped(RegressionItem)
                .where(
                    RegressionItem.run_id == run.id,
                    RegressionItem.decision == RegressionDecision.PENDING,
                )
                .order_by(RegressionItem.id)
            )
        )
        repeats = [
            item
            for item in items
            if item.kind is DependencyKind.SAME_SOURCE_REPEAT and item.block_id is not None
        ]

        blocks = {
            block.id: block
            for block in await self._session.scalars(
                self.scoped(Block)
                .where(Block.id.in_([item.block_id for item in repeats]))
                .order_by(Block.id)
                .with_for_update()
            )
        }
        currents = {
            revision.id: revision
            for revision in await self._session.scalars(
                self.scoped(TranslationRevision).where(
                    TranslationRevision.id.in_(
                        [
                            block.current_revision_id
                            for block in blocks.values()
                            if block.current_revision_id is not None
                        ]
                    )
                )
            )
        }
        approved = await approved_revisions(self._session, self.organization_id, list(currents))
        user_id = self._context.user.id

        for item in items:
            item.decided_by_id = user_id

            if item not in repeats:
                item.decision = RegressionDecision.NOT_AFFECTED
                item.note = (
                    AUTO_DIFFERENT
                    if item.kind is DependencyKind.SAME_SOURCE_REPEAT
                    else AUTO_UNSEEN
                )
                continue

            block = blocks[item.block_id]  # type: ignore[index]
            current = currents.get(block.current_revision_id)  # type: ignore[arg-type]

            if current is not None and current.text == item.proposed_text:
                item.decision = RegressionDecision.NOT_AFFECTED
                item.note = AUTO_SAME
                continue

            # Прежний текст повтора был другим — контекст мог быть другим (см. начало модуля).
            if (
                current is None
                or not item.safe
                or item.proposed_text is None
                or block.current_revision_id != item.base_revision_id
            ):
                item.decision = RegressionDecision.NOT_AFFECTED
                item.note = AUTO_DIFFERENT
                continue

            if current.stage is RevisionStage.FINAL_CANDIDATE or current.id in approved:
                item.decision = RegressionDecision.NOT_AFFECTED
                item.note = AUTO_FINAL
                continue

            number = await self._session.scalar(
                select(func.max(TranslationRevision.revision_no)).where(
                    TranslationRevision.block_id == block.id
                )
            )
            revision = TranslationRevision(
                id=uuid.uuid4(),
                organization_id=self.organization_id,
                block_id=block.id,
                revision_no=int(number or 0) + 1,
                stage=RevisionStage.WORKING,
                origin=RevisionOrigin.MODEL,
                text=item.proposed_text,
                supersedes_id=current.id,
                created_by_id=user_id,
            )
            self._session.add(revision)
            await self._session.flush()

            block.current_revision_id = revision.id
            item.decision = RegressionDecision.PROPAGATED
            item.applied_revision_id = revision.id
            item.note = AUTO_PROPAGATED

        run.status = RegressionStatus.COMPLETED

        AuditService(self._session, self._context).record(
            kind="regression.settled_automatically",
            subject_type="regression_run",
            subject_id=run.id,
            payload={
                "automatic": True,
                "propagated": sum(
                    1 for item in items if item.decision is RegressionDecision.PROPAGATED
                ),
                "not_affected": sum(
                    1 for item in items if item.decision is RegressionDecision.NOT_AFFECTED
                ),
            },
        )

    # ── виды связей ──

    async def _repeats(
        self, book_id: uuid.UUID, block: Block, old_text: str, new_text: str
    ) -> list[_Found]:
        rows = await self._session.execute(
            select(Block, TranslationRevision.text)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .outerjoin(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(
                Block.organization_id == self.organization_id,
                Chapter.book_id == book_id,
                Block.active.is_(True),
                Block.source_hash == block.source_hash,
                Block.id != block.id,
            )
            .order_by(Block.chapter_id, Block.ordinal)
            .limit(ITEM_CEILING)
        )

        return [
            _Found(
                kind=DependencyKind.SAME_SOURCE_REPEAT,
                block_id=other.id,
                base_revision_id=other.current_revision_id,
                proposed_text=new_text,
                safe=text == old_text,
            )
            for other, text in rows.all()
        ]

    async def _term_usage(
        self, book_id: uuid.UUID, block: Block, old_text: str, new_text: str
    ) -> list[_Found]:
        """Перевод термина появился в тексте или ушёл из него: книга могла разойтись."""
        glossary = await self._glossary(book_id, block.chapter_id)
        changed = [
            term
            for term in glossary.match(block.source_text)
            if term_is_used(term, old_text) != term_is_used(term, new_text)
        ]

        found: list[_Found] = []
        for term in changed:
            rows = await self._session.scalars(
                self.scoped(Block)
                .join(Chapter, Chapter.id == Block.chapter_id)
                .where(
                    Chapter.book_id == book_id,
                    Block.active.is_(True),
                    Block.id != block.id,
                    Block.source_text.icontains(term.source, autoescape=True),
                )
                .order_by(Block.chapter_id, Block.ordinal)
                .limit(ITEM_CEILING)
            )
            found.extend(
                _Found(
                    kind=DependencyKind.TERM_USAGE,
                    block_id=other.id,
                    base_revision_id=other.current_revision_id,
                )
                for other in rows
            )

        return found

    async def _objects(self, block: Block) -> list[_Found]:
        found: list[_Found] = []
        placed = await self._placed_with(block)

        if placed is not None:
            item = placed.object
            is_caption = placed.caption is not None and placed.caption.id == block.id

            # Ячейка таблицы могла разойтись с подписью, а правленая подпись — с самим рисунком.
            if item.type is ObjectType.TABLE and not is_caption and placed.caption is not None:
                found.append(
                    _Found(
                        kind=DependencyKind.TABLE_CAPTION,
                        block_id=placed.caption.id,
                        base_revision_id=placed.caption.current_revision_id,
                    )
                )
            if item.type is ObjectType.FIGURE and is_caption:
                found.append(_Found(kind=DependencyKind.FIGURE_CAPTION, object_id=item.id))

            # Те, кто упоминает этот объект.
            mentions = await self._session.scalars(
                self.scoped(Block)
                .join(ObjectReference, ObjectReference.block_id == Block.id)
                .where(ObjectReference.object_id == item.id, Block.active.is_(True))
                .order_by(Block.chapter_id, Block.ordinal)
                .limit(ITEM_CEILING)
            )
            found.extend(
                _Found(
                    kind=DependencyKind.OBJECT_REFERENCE,
                    block_id=other.id,
                    base_revision_id=other.current_revision_id,
                )
                for other in mentions
            )

        # Объекты, которые упоминает сам блок.
        mentioned = await self._session.scalars(
            self.scoped(BookObject)
            .join(ObjectReference, ObjectReference.object_id == BookObject.id)
            .where(ObjectReference.block_id == block.id)
            .order_by(BookObject.type, BookObject.number)
            .limit(ITEM_CEILING)
        )
        found.extend(
            _Found(kind=DependencyKind.OBJECT_REFERENCE, object_id=item.id) for item in mentioned
        )

        return found

    async def _cross_references(self, book_id: uuid.UUID, block: Block) -> list[_Found]:
        """Заголовок с номером: блоки, которые ссылаются на этот раздел."""
        label = _HEADING_LABEL.match(block.source_text)

        if block.kind.value != "heading" or label is None:
            return []

        # Метка — только цифры и точки: в выражение она попадает экранированной.
        pattern = (
            r"(section|chapter|раздел|глав|разд\.|гл\.)\w*\s*"
            + re.escape(label.group(1))
            + r"(\D|$)"
        )
        rows = await self._session.scalars(
            self.scoped(Block)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .where(
                Chapter.book_id == book_id,
                Block.active.is_(True),
                Block.id != block.id,
                Block.source_text.regexp_match(pattern, flags="i"),
            )
            .order_by(Block.chapter_id, Block.ordinal)
            .limit(ITEM_CEILING)
        )

        return [
            _Found(
                kind=DependencyKind.CROSS_REFERENCE,
                block_id=other.id,
                base_revision_id=other.current_revision_id,
            )
            for other in rows
        ]

    async def _adjacent(self, block: Block) -> list[_Found]:
        rows = await self._session.scalars(
            self.scoped(Block)
            .where(
                Block.chapter_id == block.chapter_id,
                Block.active.is_(True),
                Block.ordinal.in_([block.ordinal - 1, block.ordinal + 1]),
            )
            .order_by(Block.ordinal)
        )

        return [
            _Found(
                kind=DependencyKind.ADJACENT_CONTEXT,
                block_id=other.id,
                required=False,
                base_revision_id=other.current_revision_id,
            )
            for other in rows
        ]

    # ── вспомогательное ──

    async def _placed_with(self, block: Block) -> PlacedObject | None:
        master = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == block.chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )
        if master is None or not master.objects:
            return None

        listing = await ObjectService(self._session, self._context, self._storage).listing(
            master.id
        )

        for placed in listing.objects:
            own = [*placed.content, *([placed.caption] if placed.caption is not None else [])]
            if any(item.id == block.id for item in own):
                return placed

        return None

    async def _glossary(self, book_id: uuid.UUID, chapter_id: uuid.UUID) -> Glossary:
        version = await TerminologyGate(self._session, self._context).effective(book_id, chapter_id)
        if version is None:
            return Glossary([])

        return await GlossaryService(self._session, self._context).load_version(version.id)
