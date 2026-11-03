"""Редактура и финальная сверка главы.

Порядок работ держит сервер: литературная редактура идёт после технической, финальная сверка — после
литературной. Завершить можно только при полном покрытии нынешнего текста, а техническую и сверку —
ещё и без незакрытых критичных и серьёзных замечаний.

Литературная правка не должна менять то, что не про стиль. Защита сравнивает новый текст с прежним:
числа, заменители, имена из кода, ссылки, обязательные термины. Нарушение останавливает сохранение;
если редактор настаивает, правка сохраняется, но заводится техническое замечание, и оно держит
завершение работ: это и есть блокирующая проверка.
"""

import uuid
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book import BookEdition
from app.models.book_object import BookObject, ObjectReference
from app.models.chapter import Chapter
from app.models.issue import Issue, IssueCategory, IssueSeverity
from app.models.master import ChapterMaster
from app.models.organization import Role, User
from app.models.qa import QAKind
from app.models.review import (
    EditReason,
    ReviewCoverage,
    ReviewKind,
    ReviewResult,
    ReviewRun,
    ReviewStatus,
)
from app.models.translation import RevisionOrigin, RevisionStage, TranslationRevision
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.book_objects import ObjectService, PlacedObject, own_blocks
from app.services.canonical import revision_set_hash
from app.services.checks import protected_changes
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.glossary import Glossary, GlossaryService, Term
from app.services.issue_status import OPEN
from app.services.issues import IssueFilter, IssueService
from app.services.protection import stored_spans
from app.services.qa import QAService
from app.services.storage import ObjectStorage
from app.services.terminology_gate import TerminologyGate
from app.services.translation_runner import is_protected
from app.services.translation_runs import content_hash

# Новых ролей нет: ведёт редактуру тот, кто отвечает за качество.
REVIEWING_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER)
# Литературную правку вносит и переводчик: технические сущности стережёт защита, а не роль.
LITERARY_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER, Role.TRANSLATOR)

CONTEXT_BLOCKS = 2

# Что должно быть завершено раньше.
PREREQUISITE = {
    ReviewKind.LITERARY: ReviewKind.TECHNICAL,
    ReviewKind.FINAL_COMPARE: ReviewKind.LITERARY,
}
# Где незакрытые критичные и серьёзные не дают завершить.
BLOCKED_BY_ISSUES = frozenset({ReviewKind.TECHNICAL, ReviewKind.FINAL_COMPARE})


@dataclass(frozen=True, slots=True)
class Progress:
    blocks_total: int
    blocks_done: int
    objects_total: int
    objects_done: int
    untranslated: int

    @property
    def complete(self) -> bool:
        return (
            self.untranslated == 0
            and self.blocks_done == self.blocks_total
            and self.objects_done == self.objects_total
        )


@dataclass(frozen=True, slots=True)
class RunView:
    run: ReviewRun
    progress: Progress
    # Текст изменился после завершения: работа была про другой текст.
    stale: bool
    reviewer: str | None
    # Чтобы экран работы не спрашивал книгу и всю её структуру ради двух названий.
    book_title: str
    chapter_title: str | None


@dataclass(frozen=True, slots=True)
class ChapterReviews:
    technical: RunView | None
    literary: RunView | None
    final_compare: RunView | None


@dataclass(frozen=True, slots=True)
class Neighbour:
    block: Block
    translation: str | None


@dataclass(frozen=True, slots=True)
class LinkedObject:
    object: BookObject
    code: str
    # content, caption или reference: блок в объекте стоит, подписывает его или на него ссылается.
    relation: str


@dataclass(frozen=True, slots=True)
class NextItem:
    """Следующее непросмотренное место со всем, что нужно рядом."""

    block: Block | None
    current: TranslationRevision | None
    object: BookObject | None
    object_hash: str | None
    object_blocks: list[Block]
    context: list[Neighbour]
    terms: list[Term]
    # Приставка кода: глава, в которой всё это стоит.
    prefix: str
    protected: bool = False
    linked: list[LinkedObject] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    object_position: int = 0
    object_translation: str | None = None


class ReviewService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def start(self, chapter_id: uuid.UUID, kind: ReviewKind) -> RunView:
        self._context.require(*(LITERARY_ROLES if kind is ReviewKind.LITERARY else REVIEWING_ROLES))

        chapter = await self._chapter(chapter_id)
        required = PREREQUISITE.get(kind)

        if required is not None:
            earlier = await self._latest(chapter.id, required)

            if earlier is None or earlier.status is not ReviewStatus.COMPLETED:
                raise ConflictError(
                    "Литературная редактура идёт после технической"
                    if kind is ReviewKind.LITERARY
                    else "Финальная сверка идёт после литературной редактуры"
                )

        run = ReviewRun(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            kind=kind,
            status=ReviewStatus.OPEN,
            reviewer_id=self._context.user.id,
            base_revision_set_hash=revision_set_hash(await self._pairs(chapter.id)),
            created_at=datetime.now(UTC),
        )

        try:
            async with self._session.begin_nested():
                self._session.add(run)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Эта работа по главе уже открыта") from error

        self._audit("review.started", run)
        await self._session.commit()
        await self._session.refresh(run)

        return await self._view(run)

    async def of_chapter(self, chapter_id: uuid.UUID) -> ChapterReviews:
        chapter = await self._chapter(chapter_id)

        async def latest(kind: ReviewKind) -> RunView | None:
            run = await self._latest(chapter.id, kind)

            return await self._view(run) if run is not None else None

        return ChapterReviews(
            technical=await latest(ReviewKind.TECHNICAL),
            literary=await latest(ReviewKind.LITERARY),
            final_compare=await latest(ReviewKind.FINAL_COMPARE),
        )

    async def get(self, run_id: uuid.UUID) -> RunView:
        return await self._view(await self._run(run_id))

    async def next_item(
        self, run_id: uuid.UUID, *, after: int = -1, after_object: int = -1
    ) -> NextItem | None:
        """Следующее непросмотренное: сначала блоки по порядку, потом объекты.

        Пропущенное не теряется: дойдя до конца, очередь начинается сначала.
        """
        run = await self._run(run_id)
        blocks = await self._active_blocks(run.chapter_id)
        done = await self._covered_blocks(run.id)

        waiting = [
            block
            for block in blocks
            if block.current_revision_id is not None
            and (block.id, block.current_revision_id) not in done
        ]
        chosen = next((block for block in waiting if block.ordinal > after), None)
        chosen = chosen or (waiting[0] if waiting else None)

        glossary = await self._glossary(run)
        chapter = await self._chapter(run.chapter_id)
        prefix = f"{chapter.code}-" if chapter.code is not None else ""

        if chosen is not None:
            current = await self._session.get(TranslationRevision, chosen.current_revision_id)

            return NextItem(
                block=chosen,
                current=current,
                object=None,
                object_hash=None,
                object_blocks=[],
                context=await self._neighbours(blocks, chosen),
                terms=list(glossary.match(chosen.source_text)),
                prefix=prefix,
                protected=is_protected(chosen.kind, chosen.source_text),
                linked=await self._linked(run.chapter_id, chosen, prefix),
                issues=await self._open_issues(block_id=chosen.id),
            )

        objects_done = await self._covered_objects(run.id)
        placed_objects = await self._placed(run.chapter_id)
        waiting_objects = [
            (position, placed, own_blocks(placed))
            for position, placed in enumerate(placed_objects)
            if (placed.object.id, content_hash(placed.object, own_blocks(placed)))
            not in objects_done
        ]
        pick = next((row for row in waiting_objects if row[0] > after_object), None)
        pick = pick or (waiting_objects[0] if waiting_objects else None)

        if pick is None:
            return None

        position, placed, blocks_of = pick

        return NextItem(
            block=None,
            current=None,
            object=placed.object,
            object_hash=content_hash(placed.object, blocks_of),
            object_blocks=blocks_of,
            context=[],
            terms=[],
            prefix=prefix,
            issues=await self._open_issues(object_id=placed.object.id),
            object_position=position,
            object_translation=await self._translation_of(blocks_of),
        )

    async def preview_edit(
        self, run_id: uuid.UUID, *, block_id: uuid.UUID, base_revision_id: uuid.UUID, text: str
    ) -> list[str]:
        """Что правка изменит из защищённого. Сохранение проверит это ещё раз."""
        self._context.require(*LITERARY_ROLES)

        run = await self._run(run_id)
        if run.kind is not ReviewKind.LITERARY:
            raise ConflictError("Править стиль можно только в литературной редактуре")

        block = await self._session.scalar(
            self.scoped(Block).where(Block.id == block_id, Block.chapter_id == run.chapter_id)
        )
        if block is None:
            raise NotFoundError("Такого блока в этой главе нет")

        base = await self._session.scalar(
            self.scoped(TranslationRevision).where(
                TranslationRevision.id == base_revision_id, TranslationRevision.block_id == block.id
            )
        )
        if base is None:
            raise NotFoundError("Редакция не найдена")

        return await self._violations(run, block, base, text.strip())

    async def mark_block(
        self,
        run_id: uuid.UUID,
        *,
        block_id: uuid.UUID,
        revision_id: uuid.UUID,
        result: ReviewResult,
        note: str | None = None,
    ) -> RunView:
        """Отметить один блок. Отметка верна только для редакции, которую человек видел."""
        run = await self._open_run(run_id)
        self._require_marking(run)

        block = await self._session.scalar(
            self.scoped(Block).where(Block.id == block_id, Block.chapter_id == run.chapter_id)
        )
        if block is None:
            raise NotFoundError("Такого блока в этой главе нет")
        if not block.active:
            raise ConflictError("Блок больше не входит в текущую версию мастера")
        if block.current_revision_id != revision_id:
            raise ConflictError("Текст блока изменился: посмотрите его заново")

        await self._mark(run, block_id=block.id, revision_id=revision_id, result=result, note=note)

        return await self._saved(run)

    async def mark_object(
        self,
        run_id: uuid.UUID,
        *,
        object_id: uuid.UUID,
        digest: str,
        result: ReviewResult,
        note: str | None = None,
    ) -> RunView:
        run = await self._open_run(run_id)
        self._require_marking(run)

        placed = next(
            (item for item in await self._placed(run.chapter_id) if item.object.id == object_id),
            None,
        )
        if placed is None:
            raise NotFoundError("Такого объекта в этой главе нет")
        if content_hash(placed.object, own_blocks(placed)) != digest:
            raise ConflictError("Объект или его текст изменились: посмотрите его заново")

        await self._mark(run, object_id=object_id, digest=digest, result=result, note=note)

        return await self._saved(run)

    async def literary_edit(
        self,
        run_id: uuid.UUID,
        *,
        block_id: uuid.UUID,
        base_revision_id: uuid.UUID,
        text: str,
        reason: EditReason,
        note: str | None = None,
        accept_violation: bool = False,
        issue_id: uuid.UUID | None = None,
    ) -> tuple[RunView, list[str]]:
        """Литературная правка: новая редакция, защита технических сущностей."""
        self._context.require(*LITERARY_ROLES)

        run = await self._open_run(run_id)
        if run.kind is not ReviewKind.LITERARY:
            raise ConflictError("Править стиль можно только в литературной редактуре")

        block = await self._session.scalar(
            self.scoped(Block)
            .where(Block.id == block_id, Block.chapter_id == run.chapter_id)
            .with_for_update()
        )
        if block is None:
            raise NotFoundError("Такого блока в этой главе нет")
        if not block.active:
            raise ConflictError("Блок больше не входит в текущую версию мастера")
        if is_protected(block.kind, block.source_text):
            raise ConflictError("Этот блок переносится знак в знак: стиль в нём не правится")
        if block.current_revision_id != base_revision_id:
            raise ConflictError("Текст уже изменён другим редактором: сравните ещё раз")

        clean = text.strip()
        if not clean:
            raise InvalidInputError("Исправленный текст пуст")

        base = await self._session.get(TranslationRevision, base_revision_id)
        if base is None:
            raise NotFoundError("Редакция не найдена")
        if base.text == clean:
            raise InvalidInputError("Текст не изменился")

        if issue_id is not None:
            basis = await self._session.scalar(
                self.scoped(Issue).where(Issue.id == issue_id, Issue.block_id == block.id)
            )
            if basis is None:
                raise NotFoundError("Такого замечания у этого блока нет")

        violations = await self._violations(run, block, base, clean)
        comment = (note or "").strip() or None

        if violations and not accept_violation:
            raise ConflictError(
                "Правка меняет защищённое: " + "; ".join(violations) + ". Верните это или "
                "подтвердите: заведётся техническое замечание"
            )
        if violations and comment is None:
            raise InvalidInputError("Напишите, почему меняете защищённое")

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
            origin=RevisionOrigin.HUMAN,
            text=clean,
            supersedes_id=base.id,
            edit_reason=reason,
            issue_id=issue_id,
            created_by_id=self._context.user.id,
        )
        self._session.add(revision)
        await self._session.flush()
        block.current_revision_id = revision.id

        AuditService(self._session, self._context).record(
            kind="review.literary_edit",
            subject_type="block",
            subject_id=block.id,
            payload={
                "run_id": str(run.id),
                "revision_id": str(revision.id),
                "reason": reason.value,
                "violations": violations,
                "note": comment,
            },
        )

        # Нарушение не прячется: оно становится замечанием и держит завершение работ.
        if violations:
            await IssueService(self._session, self._context, self._storage).file(
                block_id=block.id,
                object_id=None,
                category=IssueCategory.TECHNICAL,
                severity=IssueSeverity.MAJOR,
                description="Литературная правка изменила защищённое: " + "; ".join(violations),
                proposed_fix=comment,
            )

        return await self._saved(run), violations

    async def complete(self, run_id: uuid.UUID) -> RunView:
        run = await self._open_run(run_id)
        self._require_marking(run)

        progress = await self._progress(run)
        if not progress.complete:
            raise ConflictError(
                "Покрытие не полное: блоков "
                f"{progress.blocks_done} из {progress.blocks_total}, объектов "
                f"{progress.objects_done} из {progress.objects_total}, без перевода "
                f"{progress.untranslated}"
            )

        if run.kind in BLOCKED_BY_ISSUES:
            stats = await IssueService(self._session, self._context, self._storage).stats(
                IssueFilter(chapter_id=run.chapter_id)
            )
            if stats.open_critical or stats.open_major:
                raise ConflictError(
                    "Остались незакрытые замечания: критичных "
                    f"{stats.open_critical}, серьёзных {stats.open_major}"
                )

        run.status = ReviewStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.completed_revision_set_hash = revision_set_hash(await self._pairs(run.chapter_id))
        self._audit("review.completed", run)

        view = await self._saved(run)

        # После стиля текст проверяется правилами заново: глазами такие потери не видны.
        if run.kind is ReviewKind.LITERARY:
            # По главе уже идёт работа: проверить можно будет с экрана главы.
            with suppress(ConflictError):
                await QAService(self._session, self._context).start(
                    run.chapter_id, QAKind.DETERMINISTIC
                )

        return view

    # ── внутреннее ──

    async def _violations(
        self, run: ReviewRun, block: Block, base: TranslationRevision, text: str
    ) -> list[str]:
        return protected_changes(
            block.source_text,
            base.text,
            text,
            glossary=await self._glossary(run),
            protected=[
                block.source_text[span.start : span.end]
                for span in stored_spans(block.source_location)
            ],
        )

    async def _open_issues(
        self, *, block_id: uuid.UUID | None = None, object_id: uuid.UUID | None = None
    ) -> list[Issue]:
        """Незакрытые замечания этого места: их не должны заводить второй раз."""
        rows = await self._session.scalars(
            self.scoped(Issue)
            .where(
                Issue.block_id == block_id
                if block_id is not None
                else Issue.object_id == object_id,
                Issue.status.in_(OPEN),
                Issue.archived_at.is_(None),
            )
            .order_by(Issue.created_at, Issue.code)
        )

        return list(rows)

    async def _linked(self, chapter_id: uuid.UUID, block: Block, prefix: str) -> list[LinkedObject]:
        """Объекты рядом с блоком: тот, где он стоит, и те, на которые он ссылается."""
        linked: dict[uuid.UUID, LinkedObject] = {}

        for placed in await self._placed(chapter_id):
            if placed.caption is not None and placed.caption.id == block.id:
                relation = "caption"
            elif any(row.id == block.id for row in placed.content):
                relation = "content"
            else:
                continue

            linked[placed.object.id] = LinkedObject(
                object=placed.object, code=prefix + placed.object.code, relation=relation
            )

        rows = await self._session.execute(
            select(BookObject, Chapter)
            .join(ObjectReference, ObjectReference.object_id == BookObject.id)
            .join(Chapter, Chapter.id == BookObject.chapter_id)
            .where(
                ObjectReference.organization_id == self.organization_id,
                ObjectReference.block_id == block.id,
            )
            .order_by(Chapter.ordinal, BookObject.type, BookObject.number)
        )
        for item, chapter in rows.all():
            if item.id not in linked:
                owner = f"{chapter.code}-" if chapter.code is not None else ""
                linked[item.id] = LinkedObject(
                    object=item, code=owner + item.code, relation="reference"
                )

        return list(linked.values())

    async def _translation_of(self, blocks: Sequence[Block]) -> str | None:
        ids = [block.current_revision_id for block in blocks if block.current_revision_id]
        if not ids:
            return None

        rows = await self._session.scalars(
            self.scoped(TranslationRevision).where(TranslationRevision.id.in_(ids))
        )
        texts = {row.id: row.text for row in rows}

        return "\n".join(
            texts[block.current_revision_id]
            for block in blocks
            if block.current_revision_id in texts
        )

    def _require_marking(self, run: ReviewRun) -> None:
        self._context.require(
            *(LITERARY_ROLES if run.kind is ReviewKind.LITERARY else REVIEWING_ROLES)
        )

    async def _mark(
        self,
        run: ReviewRun,
        *,
        block_id: uuid.UUID | None = None,
        revision_id: uuid.UUID | None = None,
        object_id: uuid.UUID | None = None,
        digest: str | None = None,
        result: ReviewResult,
        note: str | None,
    ) -> None:
        existing = await self._session.scalar(
            self.scoped(ReviewCoverage).where(
                ReviewCoverage.run_id == run.id,
                ReviewCoverage.block_id == block_id
                if block_id is not None
                else ReviewCoverage.object_id == object_id,
                ReviewCoverage.revision_id == revision_id
                if block_id is not None
                else ReviewCoverage.content_hash == digest,
            )
        )
        if existing is not None:
            raise ConflictError("Это место уже отмечено")

        self._session.add(
            ReviewCoverage(
                organization_id=self.organization_id,
                run_id=run.id,
                block_id=block_id,
                revision_id=revision_id,
                object_id=object_id,
                content_hash=digest,
                result=result,
                reviewer_id=self._context.user.id,
                note=(note or "").strip() or None,
            )
        )

    async def _progress(self, run: ReviewRun) -> Progress:
        blocks = await self._active_blocks(run.chapter_id)
        done = await self._covered_blocks(run.id)
        objects_done = await self._covered_objects(run.id)
        placed = await self._placed(run.chapter_id)

        translated = [block for block in blocks if block.current_revision_id is not None]

        return Progress(
            blocks_total=len(blocks),
            blocks_done=sum(
                1 for block in translated if (block.id, block.current_revision_id) in done
            ),
            objects_total=len(placed),
            objects_done=sum(
                1
                for item in placed
                if (item.object.id, content_hash(item.object, own_blocks(item))) in objects_done
            ),
            untranslated=len(blocks) - len(translated),
        )

    async def _view(self, run: ReviewRun) -> RunView:
        progress = await self._progress(run)
        stale = (
            run.status is ReviewStatus.COMPLETED
            and run.completed_revision_set_hash
            != revision_set_hash(await self._pairs(run.chapter_id))
        )

        chapter = await self._chapter(run.chapter_id)
        book = await self._session.get_one(BookEdition, run.book_id)
        reviewer = (
            await self._session.get(User, run.reviewer_id) if run.reviewer_id is not None else None
        )

        return RunView(
            run=run,
            progress=progress,
            stale=stale,
            reviewer=reviewer.email if reviewer is not None else None,
            book_title=book.title,
            chapter_title=chapter.title,
        )

    async def _saved(self, run: ReviewRun) -> RunView:
        await self._session.commit()
        await self._session.refresh(run)

        return await self._view(run)

    def _audit(self, kind: str, run: ReviewRun) -> None:
        AuditService(self._session, self._context).record(
            kind=kind,
            subject_type="review_run",
            subject_id=run.id,
            payload={
                "chapter_id": str(run.chapter_id),
                "kind": run.kind.value,
                "base_revision_set_hash": run.base_revision_set_hash,
                "completed_revision_set_hash": run.completed_revision_set_hash,
            },
        )

    async def _run(self, run_id: uuid.UUID) -> ReviewRun:
        run = await self._session.scalar(self.scoped(ReviewRun).where(ReviewRun.id == run_id))
        if run is None:
            raise NotFoundError("Такой работы нет")

        return run

    async def _open_run(self, run_id: uuid.UUID) -> ReviewRun:
        run = await self._session.scalar(
            self.scoped(ReviewRun).where(ReviewRun.id == run_id).with_for_update()
        )
        if run is None:
            raise NotFoundError("Такой работы нет")
        if run.status is not ReviewStatus.OPEN:
            raise ConflictError("Эта работа уже завершена")

        return run

    async def _latest(self, chapter_id: uuid.UUID, kind: ReviewKind) -> ReviewRun | None:
        found: ReviewRun | None = await self._session.scalar(
            self.scoped(ReviewRun)
            .where(ReviewRun.chapter_id == chapter_id, ReviewRun.kind == kind)
            .order_by(ReviewRun.created_at.desc())
            .limit(1)
        )

        return found

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _active_blocks(self, chapter_id: uuid.UUID) -> list[Block]:
        rows = await self._session.scalars(
            self.scoped(Block)
            .where(Block.chapter_id == chapter_id, Block.active.is_(True))
            .order_by(Block.ordinal)
        )

        return list(rows)

    async def _pairs(self, chapter_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
        return [
            (block.id, block.current_revision_id) for block in await self._active_blocks(chapter_id)
        ]

    async def _covered_blocks(self, run_id: uuid.UUID) -> set[tuple[uuid.UUID, uuid.UUID]]:
        rows = await self._session.execute(
            select(ReviewCoverage.block_id, ReviewCoverage.revision_id).where(
                ReviewCoverage.run_id == run_id, ReviewCoverage.block_id.is_not(None)
            )
        )

        return {(row[0], row[1]) for row in rows.all()}

    async def _covered_objects(self, run_id: uuid.UUID) -> set[tuple[uuid.UUID, str]]:
        rows = await self._session.execute(
            select(ReviewCoverage.object_id, ReviewCoverage.content_hash).where(
                ReviewCoverage.run_id == run_id, ReviewCoverage.object_id.is_not(None)
            )
        )

        return {(row[0], row[1]) for row in rows.all()}

    async def _placed(self, chapter_id: uuid.UUID) -> list[PlacedObject]:
        master = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )
        if master is None:
            return []

        listing = await ObjectService(self._session, self._context, self._storage).listing(
            master.id
        )

        return [item for item in listing.objects if item.object.active]

    async def _neighbours(self, blocks: Sequence[Block], chosen: Block) -> list[Neighbour]:
        index = next(i for i, block in enumerate(blocks) if block.id == chosen.id)
        around = [
            *blocks[max(0, index - CONTEXT_BLOCKS) : index],
            *blocks[index + 1 : index + 1 + CONTEXT_BLOCKS],
        ]
        ids = [block.current_revision_id for block in around if block.current_revision_id]
        rows: Iterable[TranslationRevision] = (
            await self._session.scalars(
                self.scoped(TranslationRevision).where(TranslationRevision.id.in_(ids))
            )
            if ids
            else []
        )
        texts = {row.id: row.text for row in rows}

        return [
            Neighbour(
                block=block,
                translation=texts.get(block.current_revision_id)
                if block.current_revision_id is not None
                else None,
            )
            for block in around
        ]

    async def _glossary(self, run: ReviewRun) -> Glossary:
        version = await TerminologyGate(self._session, self._context).effective(
            run.book_id, run.chapter_id
        )
        if version is None:
            return Glossary([])

        return await GlossaryService(self._session, self._context).load_version(version.id)
