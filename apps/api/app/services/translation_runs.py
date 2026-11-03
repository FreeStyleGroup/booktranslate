"""Перевод главы глазами человека: запуск, перевод заново, история редакций.

Запустить перевод можно, только когда глава к нему готова: утверждены границы
и мастер, открыт гейт терминологии. Обход гейта есть, но он отдельное решение:
только администратор, только с причиной, с записью в журнал и с отметкой на
прогоне — такие блоки подлежат повторной проверке перед выпуском. Границы и
мастер обойти нельзя: это не вопрос терминов, а вопрос того, что переводим.

«Перевести заново» называет не только блоки, но и редакции, относительно
которых просит вариант. Если текущая редакция уже другая, запрос отвергается:
человек сравнивал бы новый вариант не с тем текстом, на который смотрел.
Текущую редакцию перевод заново не меняет — вариант становится текущим только
решением человека (`adopt`).
"""

import difflib
import hashlib
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.block import Block
from app.models.book_object import BookObject
from app.models.chapter import Chapter
from app.models.glossary_version import GlossaryVersion
from app.models.job import LIVE, JobKind, JobState, TranslationJob
from app.models.master import ChapterMaster
from app.models.organization import Role, User
from app.models.translation import (
    ObjectVerification,
    RunKind,
    TranslationRevision,
    TranslationRun,
)
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.providers import provider_info
from app.services.terminology_gate import Gate, GateItem, TerminologyGate
from app.services.translation_runner import is_protected
from app.services.workspace import model_for

TRANSLATING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)
EDITING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER)

# Эти причины обойти нельзя: они не о терминах, а о том, что переводим.
HARD_BLOCKERS = frozenset({"boundaries_draft", "master_missing", "master_not_approved"})

REASON_MIN = 10
REASON_MAX = 1000
# Перевод заново — точечная работа: всю главу переводят не так.
MAX_RETRANSLATE = 500

# Для сравнения редакций слово с пробелами вокруг — одна единица.
_WORDS = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Change:
    """Участок сравнения двух редакций."""

    op: str  # equal, insert, delete
    text: str


@dataclass(frozen=True, slots=True)
class RunView:
    run: TranslationRun
    job: TranslationJob | None
    glossary_label: str | None


@dataclass(slots=True)
class Readiness:
    """Можно ли переводить главу и что об этом известно прямо сейчас."""

    chapter: Chapter
    gate: Gate
    master: ChapterMaster | None
    blockers: list[GateItem]
    total: int
    translated: int
    # Нечем заняться, пока идёт прогон: кнопка на экране опирается на это.
    live: RunView | None = None
    latest: RunView | None = None

    @property
    def pending(self) -> int:
        return self.total - self.translated

    @property
    def open(self) -> bool:
        return not self.blockers

    @property
    def bypassable(self) -> bool:
        """Есть причины, и все они о терминах: администратор вправе обойти."""
        return bool(self.blockers) and all(item.code not in HARD_BLOCKERS for item in self.blockers)


@dataclass(frozen=True, slots=True)
class RetranslateItem:
    block_id: uuid.UUID
    base_revision_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class BlockRow:
    """Блок главы рядом с его текущей редакцией."""

    block: Block
    current: TranslationRevision | None
    # Варианты, созданные позже текущей редакции, — их ещё не приняли.
    variants: int = 0


@dataclass(frozen=True, slots=True)
class BlockPage:
    total: int
    items: list[BlockRow]


@dataclass(frozen=True, slots=True)
class RevisionView:
    """Редакция и то, откуда она взялась: модель, промпт, глоссарий, прогон."""

    revision: TranslationRevision
    current: bool
    run: TranslationRun | None
    glossary_label: str | None
    author: str | None
    # Сравнение с редакцией, на основе которой создана эта, или с предыдущей.
    changes: list[Change] = field(default_factory=list)
    compared_with: int | None = None


@dataclass(frozen=True, slots=True)
class VerificationState:
    """Отметка «проверено технически» и действует ли она сейчас."""

    verified: bool
    verified_at: datetime | None = None
    verified_by: str | None = None
    # Отметка есть, но содержимое с тех пор изменилось.
    outdated: bool = False


def compare(before: str, after: str) -> list[Change]:
    """Сравнение двух редакций по словам.

    По словам, а не по знакам: «клапан» и «клапана» должны показываться как
    замена слова, а не как одна вставленная буква посреди него.
    """
    left = _WORDS.findall(before)
    right = _WORDS.findall(after)
    changes: list[Change] = []

    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(
        a=left, b=right, autojunk=False
    ).get_opcodes():
        if op == "equal":
            changes.append(Change("equal", "".join(left[a1:a2])))
            continue

        if a2 > a1:
            changes.append(Change("delete", "".join(left[a1:a2])))
        if b2 > b1:
            changes.append(Change("insert", "".join(right[b1:b2])))

    return changes


class ChapterTranslationService(TenantService):
    async def readiness(self, chapter_id: uuid.UUID) -> Readiness:
        gate = await TerminologyGate(self._session, self._context).check(chapter_id)
        chapter = gate.state.chapter
        master = gate.state.master
        blockers = list(gate.blockers)

        if master is not None and master.approved_at is None:
            blockers.insert(
                0,
                GateItem(
                    "master_not_approved",
                    f"Мастер {master.label} не утверждён: сначала проверьте, что текст извлечён "
                    "верно",
                    chapter_id=chapter.id,
                ),
            )

        total, translated = await self._counts(chapter.id)
        runs = await self.runs(chapter.id, limit=1)
        latest = runs[0] if runs else None
        live = latest if latest is not None and _is_live(latest) else None

        return Readiness(
            chapter=chapter,
            gate=gate,
            master=master,
            blockers=blockers,
            total=total,
            translated=translated,
            live=live,
            latest=latest,
        )

    async def start(
        self, chapter_id: uuid.UUID, *, ignore_terminology: bool = False, reason: str | None = None
    ) -> RunView:
        """Поставить в очередь перевод всего, что в главе ещё не переведено."""
        self._context.require(*TRANSLATING_ROLES)

        readiness = await self.readiness(chapter_id)
        why = self._admit(readiness, ignore_terminology=ignore_terminology, reason=reason)

        if readiness.pending == 0:
            raise ConflictError("В главе не осталось непереведённых блоков")

        return await self._launch(
            readiness, kind=RunKind.DRAFT, selection=[], total=readiness.pending, why=why
        )

    async def retranslate(
        self,
        chapter_id: uuid.UUID,
        items: Sequence[RetranslateItem],
        *,
        ignore_terminology: bool = False,
        reason: str | None = None,
    ) -> RunView:
        """Получить вариант перевода выбранных блоков рядом с текущей редакцией."""
        self._context.require(*TRANSLATING_ROLES)

        if not items:
            raise InvalidInputError("Не выбрано ни одного блока")

        if len(items) > MAX_RETRANSLATE:
            raise InvalidInputError(f"За один раз можно выбрать не больше {MAX_RETRANSLATE} блоков")

        readiness = await self.readiness(chapter_id)
        why = self._admit(readiness, ignore_terminology=ignore_terminology, reason=reason)

        blocks = {
            block.id: block
            for block in await self._session.scalars(
                self.scoped(Block).where(
                    Block.chapter_id == chapter_id,
                    Block.active.is_(True),
                    Block.id.in_([item.block_id for item in items]),
                )
            )
        }
        selection = []

        for item in items:
            block = blocks.get(item.block_id)

            if block is None:
                raise InvalidInputError("Блок не входит в текущую версию мастера главы")

            if is_protected(block.kind, block.source_text):
                raise InvalidInputError(
                    f"Блок {block.code} не переводится: это защищённое содержимое"
                )

            # Запрос называет то, что человек видел. Другая текущая редакция
            # значит, что он сравнивал бы вариант не с тем текстом.
            if block.current_revision_id != item.base_revision_id:
                raise ConflictError(
                    f"Текущая редакция блока {block.code} изменилась — обновите страницу"
                )

            selection.append(
                {
                    "block_id": str(block.id),
                    "base_revision_id": (
                        str(item.base_revision_id) if item.base_revision_id else None
                    ),
                }
            )

        return await self._launch(
            readiness, kind=RunKind.RETRANSLATE, selection=selection, total=len(selection), why=why
        )

    def _admit(
        self, readiness: Readiness, *, ignore_terminology: bool, reason: str | None
    ) -> str | None:
        """Пропустить запуск или объяснить, почему нельзя. Возвращает причину обхода."""
        if readiness.open:
            return None

        hard = [item for item in readiness.blockers if item.code in HARD_BLOCKERS]
        if hard:
            raise ConflictError(hard[0].message)

        if not ignore_terminology:
            raise ConflictError(readiness.blockers[0].message)

        # Обход только у администратора. Владелец проходит проверку сам.
        self._context.require(Role.ADMIN)

        why = (reason or "").strip()
        if not REASON_MIN <= len(why) <= REASON_MAX:
            raise InvalidInputError(
                f"Обход гейта требует причины: от {REASON_MIN} до {REASON_MAX} знаков"
            )

        return why

    async def _launch(
        self,
        readiness: Readiness,
        *,
        kind: RunKind,
        selection: list[dict[str, str | None]],
        total: int,
        why: str | None,
    ) -> RunView:
        if readiness.master is None:
            raise ConflictError("У главы нет мастера")

        chapter = readiness.chapter
        info = provider_info(await model_for(self._session, self.organization_id))
        version = readiness.gate.version
        run = TranslationRun(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            master_id=readiness.master.id,
            kind=kind,
            provider=info.provider,
            model=info.model,
            prompt_version=info.prompt_version,
            glossary_version_id=version.id if version is not None else None,
            ignore_terminology=why is not None,
            bypass_reason=why,
            selection=selection,
            requested_by_id=self._context.user.id,
            blocks_total=total,
            from_model=0,
            from_memory=0,
            copied=0,
            rejections=[],
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cache_write_tokens=0,
        )
        job = TranslationJob(
            organization_id=self.organization_id,
            kind=JobKind.CHAPTER,
            chapter_id=chapter.id,
            run_id=run.id,
            state=JobState.WAITING,
            requested_by_id=self._context.user.id,
            segments_total=total,
        )

        audit = AuditService(self._session, self._context)
        audit.record(
            kind="translation.started",
            subject_type="translation_run",
            subject_id=run.id,
            payload={
                "chapter_id": str(chapter.id),
                "chapter_code": chapter.code,
                "kind": kind.value,
                "blocks": total,
                "model": info.model,
                "prompt_version": info.prompt_version,
                "glossary_version_id": str(version.id) if version is not None else None,
            },
        )

        if why is not None:
            audit.record(
                kind="translation.gate_bypassed",
                subject_type="translation_run",
                subject_id=run.id,
                payload={
                    "chapter_id": str(chapter.id),
                    "chapter_code": chapter.code,
                    "reason": why,
                    "blockers": [item.code for item in readiness.blockers],
                },
            )

        try:
            # По шагам: связей ORM нет, а задание ссылается на прогон.
            self._session.add(run)
            await self._session.flush()
            self._session.add(job)
            await self._session.commit()
        except IntegrityError as error:
            # Одна глава — один живой прогон; ограничение стоит в базе, и два
            # одновременных нажатия проверку выше проходят оба.
            await self._session.rollback()
            raise ConflictError("Глава уже переводится") from error

        await self._session.refresh(run)
        await self._session.refresh(job)

        return RunView(
            run=run, job=job, glossary_label=version.label if version is not None else None
        )

    async def runs(self, chapter_id: uuid.UUID, *, limit: int = 20) -> list[RunView]:
        """Прогоны главы, новые первыми."""
        await self._chapter(chapter_id)

        rows = await self._session.execute(
            select(TranslationRun, TranslationJob, GlossaryVersion)
            .outerjoin(TranslationJob, TranslationJob.run_id == TranslationRun.id)
            .outerjoin(GlossaryVersion, GlossaryVersion.id == TranslationRun.glossary_version_id)
            .where(
                TranslationRun.organization_id == self.organization_id,
                TranslationRun.chapter_id == chapter_id,
            )
            .order_by(TranslationRun.created_at.desc(), TranslationRun.id)
            .limit(limit)
        )

        return [
            RunView(run=run, job=job, glossary_label=version.label if version else None)
            for run, job, version in rows.all()
        ]

    async def blocks(self, chapter_id: uuid.UUID, *, limit: int, offset: int) -> BlockPage:
        """Текущие блоки главы по порядку — рядом с их текущими редакциями."""
        await self._chapter(chapter_id)

        condition = (
            Block.organization_id == self.organization_id,
            Block.chapter_id == chapter_id,
            Block.active.is_(True),
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(Block).where(*condition))
            or 0
        )
        rows = await self._session.execute(
            select(Block, TranslationRevision)
            .outerjoin(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(*condition)
            .order_by(Block.ordinal)
            .limit(limit)
            .offset(offset)
        )
        pairs = rows.all()
        variants = await self._variant_counts([(block.id, current) for block, current in pairs])

        return BlockPage(
            total=total,
            items=[
                BlockRow(block=block, current=current, variants=variants.get(block.id, 0))
                for block, current in pairs
            ],
        )

    async def _variant_counts(
        self, pairs: list[tuple[uuid.UUID, TranslationRevision | None]]
    ) -> dict[uuid.UUID, int]:
        """Сколько у блока редакций новее текущей."""
        ids = [block_id for block_id, _ in pairs]
        if not ids:
            return {}

        rows = await self._session.execute(
            select(TranslationRevision.block_id, TranslationRevision.revision_no).where(
                TranslationRevision.block_id.in_(ids)
            )
        )
        numbers = {
            block_id: (current.revision_no if current is not None else 0)
            for block_id, current in pairs
        }
        counts: dict[uuid.UUID, int] = {}

        for block_id, number in rows.all():
            if number > numbers[block_id]:
                counts[block_id] = counts.get(block_id, 0) + 1

        return counts

    async def history(self, block_id: uuid.UUID) -> tuple[Block, list[RevisionView]]:
        """Все редакции блока, новые первыми, с происхождением и сравнением."""
        block = await self._block(block_id)
        rows = (
            await self._session.execute(
                select(TranslationRevision, TranslationRun, GlossaryVersion, User)
                .outerjoin(TranslationRun, TranslationRun.id == TranslationRevision.run_id)
                .outerjoin(
                    GlossaryVersion, GlossaryVersion.id == TranslationRun.glossary_version_id
                )
                .outerjoin(User, User.id == TranslationRevision.created_by_id)
                .where(TranslationRevision.block_id == block.id)
                .order_by(TranslationRevision.revision_no.desc())
            )
        ).all()

        by_id = {row[0].id: row[0] for row in rows}
        views = []

        for index, (revision, run, version, author) in enumerate(rows):
            previous = rows[index + 1][0] if index + 1 < len(rows) else None
            base = by_id.get(revision.supersedes_id) if revision.supersedes_id else previous

            views.append(
                RevisionView(
                    revision=revision,
                    current=revision.id == block.current_revision_id,
                    run=run,
                    glossary_label=version.label if version is not None else None,
                    author=author.email if author is not None else None,
                    changes=compare(base.text, revision.text) if base is not None else [],
                    compared_with=base.revision_no if base is not None else None,
                )
            )

        return block, views

    async def adopt(self, revision_id: uuid.UUID) -> Block:
        """Принять вариант: сделать редакцию текущей.

        Вариант сравнивали с редакцией, на основе которой он создан. Если текущая
        с тех пор другая, решение принималось о другом тексте, и его надо принять
        заново, глядя на то, что есть сейчас. Прежняя редакция никуда не девается.
        """
        self._context.require(*EDITING_ROLES)

        revision = await self._session.scalar(
            self.scoped(TranslationRevision).where(TranslationRevision.id == revision_id)
        )
        if revision is None:
            raise NotFoundError("Редакция не найдена")

        block = await self._session.scalar(
            self.scoped(Block).where(Block.id == revision.block_id).with_for_update()
        )
        if block is None:
            raise NotFoundError("Блок не найден")

        if not block.active:
            raise ConflictError("Блок больше не входит в текущую версию мастера")

        if revision.id == block.current_revision_id:
            raise ConflictError("Эта редакция уже текущая")

        if revision.supersedes_id != block.current_revision_id:
            raise ConflictError(
                "Текущая редакция изменилась после создания этого варианта — сравните заново"
            )

        previous = block.current_revision_id
        block.current_revision_id = revision.id

        AuditService(self._session, self._context).record(
            kind="translation.revision_adopted",
            subject_type="block",
            subject_id=block.id,
            payload={
                "revision_id": str(revision.id),
                "revision_no": revision.revision_no,
                "previous_revision_id": str(previous) if previous else None,
            },
        )

        await self._session.commit()
        await self._session.refresh(block)

        return block

    async def current_texts(self, block_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Текст текущей редакции каждого блока — у кого она есть."""
        if not block_ids:
            return {}

        rows = await self._session.execute(
            select(Block.id, TranslationRevision.text)
            .join(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(Block.organization_id == self.organization_id, Block.id.in_(block_ids))
        )

        return {block_id: revision_text for block_id, revision_text in rows.all()}

    async def object_state(self, item: BookObject, blocks: Sequence[Block]) -> VerificationState:
        """Действует ли отметка «проверено технически» у объекта."""
        latest = await self._session.execute(
            select(ObjectVerification, User)
            .outerjoin(User, User.id == ObjectVerification.verified_by_id)
            .where(
                ObjectVerification.organization_id == self.organization_id,
                ObjectVerification.object_id == item.id,
            )
            .order_by(ObjectVerification.created_at.desc())
            .limit(1)
        )
        row = latest.first()

        if row is None:
            return VerificationState(verified=False)

        verification, user = row
        valid = verification.content_hash == content_hash(item, blocks)

        return VerificationState(
            verified=valid,
            verified_at=verification.verified_at,
            verified_by=user.email if user is not None else None,
            outdated=not valid,
        )

    async def verify_object(self, item: BookObject, blocks: Sequence[Block]) -> VerificationState:
        """Отметить, что объект проверен технически.

        У объекта с текстом непереведённого быть не должно: проверять перевод,
        которого нет, нечего.
        """
        self._context.require(*EDITING_ROLES)

        lacking = [block.code for block in blocks if block.current_revision_id is None]
        if lacking:
            raise ConflictError("У объекта есть непереведённые блоки: " + ", ".join(lacking[:5]))

        now = datetime.now(UTC)
        digest = content_hash(item, blocks)

        self._session.add(
            ObjectVerification(
                organization_id=self.organization_id,
                object_id=item.id,
                content_hash=digest,
                verified_by_id=self._context.user.id,
                verified_at=now,
            )
        )
        AuditService(self._session, self._context).record(
            kind="object.verified",
            subject_type="book_object",
            subject_id=item.id,
            payload={"content_hash": digest, "checksum": item.checksum},
        )
        await self._session.commit()

        return VerificationState(
            verified=True, verified_at=now, verified_by=self._context.user.email
        )

    async def _counts(self, chapter_id: uuid.UUID) -> tuple[int, int]:
        row = (
            await self._session.execute(
                select(func.count(), func.count(Block.current_revision_id)).where(
                    Block.organization_id == self.organization_id,
                    Block.chapter_id == chapter_id,
                    Block.active.is_(True),
                )
            )
        ).one()

        return int(row[0]), int(row[1])

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _block(self, block_id: uuid.UUID) -> Block:
        block = await self._session.scalar(self.scoped(Block).where(Block.id == block_id))
        if block is None:
            raise NotFoundError("Блок не найден")

        return block


def _is_live(view: RunView) -> bool:
    return view.job is not None and view.job.state in LIVE


def content_hash(item: BookObject, blocks: Sequence[Block]) -> str:
    """Сумма того, что проверяли: объект и текущие редакции его блоков."""
    parts = [item.checksum, *sorted(str(block.current_revision_id) for block in blocks)]

    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
