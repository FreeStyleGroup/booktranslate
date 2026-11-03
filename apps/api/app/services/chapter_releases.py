"""Финальная версия главы: что мешает её создать, манифест, утверждение, разница с рабочим текстом.

Причины, которые держат главу, отдаются списком с кодами: человек видит их заранее, а
автоматический режим решает по ним, идти дальше или ждать человека. Создание и утверждение
проверяют то же самое ещё раз: между показом и нажатием всё могло измениться.

Глава в обход гейта терминологии отдельной причиной не держится. Такой текст и так обязан пройти
гейт, формальные проверки и финальную сверку уже здесь: это и есть его повторная проверка.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book import BookEdition
from app.models.chapter import BoundaryStatus, Chapter
from app.models.issue import Issue
from app.models.job import LIVE, TranslationJob
from app.models.master import ChapterMaster
from app.models.organization import Role, User
from app.models.regression import (
    RegressionDecision,
    RegressionItem,
    RegressionRun,
    RegressionStatus,
)
from app.models.release import ChapterRelease, ReleaseStatus
from app.models.review import ReviewKind, ReviewRun, ReviewStatus
from app.models.translation import TranslationRevision
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.book_objects import ObjectService, own_blocks
from app.services.canonical import canonical_json, revision_set_hash
from app.services.context import RequestContext
from app.services.errors import ConflictError, NotFoundError
from app.services.issues import IssueFilter, IssueService
from app.services.qa import QAService
from app.services.reviews import ReviewService
from app.services.storage import ObjectStorage
from app.services.terminology_gate import TerminologyGate
from app.services.translation_runs import Change, compare, content_hash

MANIFEST_SCHEMA = 1

# Создаёт и отменяет тот, кто ведёт книгу; утвердить может и проверяющий.
CREATING_ROLES = (Role.ADMIN, Role.MANAGER)
APPROVING_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER)


@dataclass(frozen=True, slots=True)
class Blocker:
    """Что держит главу: код для машины, фраза для человека."""

    code: str
    message: str
    count: int | None = None


@dataclass(frozen=True, slots=True)
class Reviews:
    technical: ReviewRun | None
    literary: ReviewRun | None
    final_compare: ReviewRun | None


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    blockers: list[Blocker]
    reviews: Reviews
    master: ChapterMaster | None

    @property
    def ready(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class ReleaseView:
    release: ChapterRelease
    creator: str | None
    approver: str | None
    # Рабочий текст ушёл вперёд от этой версии.
    working_differs: bool


@dataclass(frozen=True, slots=True)
class WorkingChange:
    """Блок, текст которого в рабочей версии и в финальной различается."""

    block_id: uuid.UUID
    code: str
    final_text: str | None
    working_text: str | None
    changes: list[Change]


class ChapterReleaseService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def gate(self, chapter_id: uuid.UUID) -> ReleaseGate:
        chapter = await self._chapter(chapter_id)
        master = await self._master(chapter.id)
        blockers: list[Blocker] = []

        if chapter.boundary_status is not BoundaryStatus.APPROVED:
            blockers.append(Blocker("boundaries_not_approved", "Границы главы не утверждены"))
        if master is None:
            blockers.append(Blocker("no_master", "У главы нет мастера"))
        elif master.approved_at is None:
            blockers.append(Blocker("master_not_approved", "Мастер главы не утверждён"))

        terminology = await TerminologyGate(self._session, self._context).check(chapter.id)
        blockers.extend(Blocker(item.code, item.message) for item in terminology.blockers)

        if await self._job_is_live(chapter.id):
            blockers.append(Blocker("job_running", "По главе идёт работа: дождитесь её конца"))

        checks = await QAService(self._session, self._context).state(chapter.id)
        if checks.translated < checks.total:
            missing = checks.total - checks.translated
            blockers.append(Blocker("untranslated", f"Не переведено блоков: {missing}", missing))
        if checks.formal < checks.translated:
            missing = checks.translated - checks.formal
            blockers.append(
                Blocker(
                    "formal_incomplete",
                    f"Формальная проверка не покрыла блоков: {missing}. Запустите её заново",
                    missing,
                )
            )

        stats = await IssueService(self._session, self._context, self._storage).stats(
            IssueFilter(chapter_id=chapter.id)
        )
        if stats.open_critical:
            blockers.append(
                Blocker(
                    "open_critical",
                    f"Незакрытых критичных замечаний: {stats.open_critical}",
                    stats.open_critical,
                )
            )
        if stats.open_major:
            blockers.append(
                Blocker(
                    "open_major",
                    f"Незакрытых серьёзных замечаний: {stats.open_major}",
                    stats.open_major,
                )
            )

        pending = await self._pending_regression(chapter.id)
        if pending:
            blockers.append(
                Blocker("regression_pending", f"Не решено мест в регрессии: {pending}", pending)
            )

        reviews = Reviews(
            technical=await self._completed(chapter.id, ReviewKind.TECHNICAL),
            literary=await self._completed(chapter.id, ReviewKind.LITERARY),
            final_compare=await self._completed(chapter.id, ReviewKind.FINAL_COMPARE),
        )
        if reviews.technical is None:
            blockers.append(Blocker("technical_missing", "Техническая редактура не завершена"))
        if reviews.literary is None:
            blockers.append(Blocker("literary_missing", "Литературная редактура не завершена"))
        if reviews.final_compare is None:
            blockers.append(Blocker("final_missing", "Финальная сверка не завершена"))
        elif (
            reviews.final_compare.completed_revision_set_hash != checks.revision_set_hash
            or await self._coverage_gap(reviews.final_compare)
        ):
            blockers.append(
                Blocker(
                    "final_stale",
                    "После финальной сверки текст изменился: её покрытие меньше 100%",
                )
            )

        return ReleaseGate(blockers=blockers, reviews=reviews, master=master)

    async def of_chapter(self, chapter_id: uuid.UUID) -> list[ReleaseView]:
        chapter = await self._chapter(chapter_id)
        rows = await self._session.scalars(
            self.scoped(ChapterRelease)
            .where(ChapterRelease.chapter_id == chapter.id)
            .order_by(ChapterRelease.version_major.desc(), ChapterRelease.version_minor.desc())
        )
        current = revision_set_hash(await self._pairs(chapter.id))

        return [await self._view(row, current) for row in rows]

    async def get(self, release_id: uuid.UUID) -> ReleaseView:
        release = await self._release(release_id)

        return await self._view(release, revision_set_hash(await self._pairs(release.chapter_id)))

    async def create(self, chapter_id: uuid.UUID, *, major: bool = False) -> ReleaseView:
        """Создать версию. Глава блокируется: две сразу получили бы один номер."""
        self._context.require(*CREATING_ROLES)

        chapter = await self._session.scalar(
            self.scoped(Chapter).where(Chapter.id == chapter_id).with_for_update()
        )
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        gate = await self.gate(chapter.id)
        if not gate.ready:
            raise ConflictError(
                "Финальную версию создать нельзя: "
                + "; ".join(item.message for item in gate.blockers)
            )

        assert gate.master is not None
        assert gate.reviews.technical is not None
        assert gate.reviews.literary is not None
        assert gate.reviews.final_compare is not None

        draft = await self._session.scalar(
            self.scoped(ChapterRelease).where(
                ChapterRelease.chapter_id == chapter.id,
                ChapterRelease.status == ReleaseStatus.DRAFT,
            )
        )
        if draft is not None:
            raise ConflictError(f"{draft.code} ещё не утверждена: утвердите её или отмените")

        terminology = await TerminologyGate(self._session, self._context).effective(
            chapter.book_id, chapter.id
        )
        manifest = await self._manifest(chapter, gate.master, terminology)
        digest = hash_manifest(manifest)

        latest = await self._session.scalar(
            self.scoped(ChapterRelease)
            .where(ChapterRelease.chapter_id == chapter.id)
            .order_by(ChapterRelease.version_major.desc(), ChapterRelease.version_minor.desc())
            .limit(1)
        )
        if latest is not None and latest.manifest_hash == digest:
            raise ConflictError(f"Текст главы не изменился с {latest.code}")

        version = _next_version(latest, major=major)
        book_code = await self._book_code(chapter)
        release = ChapterRelease(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            version_major=version[0],
            version_minor=version[1],
            code=f"{book_code}-{chapter.code}-FINAL-v{version[0]}.{version[1]}",
            status=ReleaseStatus.DRAFT,
            manifest=manifest,
            manifest_hash=digest,
            revision_set_hash=revision_set_hash(await self._pairs(chapter.id)),
            master_id=gate.master.id,
            glossary_version_id=terminology.id if terminology is not None else None,
            technical_review_id=gate.reviews.technical.id,
            literary_review_id=gate.reviews.literary.id,
            final_compare_id=gate.reviews.final_compare.id,
            created_by_id=self._context.user.id,
        )

        try:
            async with self._session.begin_nested():
                self._session.add(release)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Версию уже создают: обновите страницу") from error

        self._audit("chapter_release.created", release)
        await self._session.commit()
        await self._session.refresh(release)

        return await self.get(release.id)

    async def approve(self, release_id: uuid.UUID) -> ReleaseView:
        self._context.require(*APPROVING_ROLES)

        release = await self._locked(release_id)
        if release.status is not ReleaseStatus.DRAFT:
            raise ConflictError(f"{release.code} уже утверждена")

        current = revision_set_hash(await self._pairs(release.chapter_id))
        if current != release.revision_set_hash:
            raise ConflictError(
                f"Текст главы изменился после создания {release.code}: создайте новую версию"
            )

        gate = await self.gate(release.chapter_id)
        if not gate.ready:
            raise ConflictError(
                "Утвердить нельзя: " + "; ".join(item.message for item in gate.blockers)
            )

        release.status = ReleaseStatus.APPROVED
        release.approved_by_id = self._context.user.id
        release.approved_at = datetime.now(UTC)
        self._audit("chapter_release.approved", release)
        await self._session.commit()
        await self._session.refresh(release)

        return await self.get(release.id)

    async def discard(self, release_id: uuid.UUID) -> None:
        """Отменить черновик. Утверждённую версию база удалить не даст."""
        self._context.require(*CREATING_ROLES)

        release = await self._locked(release_id)
        if release.status is not ReleaseStatus.DRAFT:
            raise ConflictError(f"{release.code} утверждена и не отменяется")

        self._audit("chapter_release.discarded", release)
        await self._session.delete(release)
        await self._session.commit()

    async def changes(self, release_id: uuid.UUID) -> list[WorkingChange]:
        """Чем рабочий текст отличается от этой версии, в порядке главы."""
        release = await self._release(release_id)
        kept = {uuid.UUID(row["id"]): row for row in release.manifest["blocks"]}
        blocks = list(
            await self._session.scalars(
                self.scoped(Block)
                .where(
                    Block.chapter_id == release.chapter_id,
                    (Block.active.is_(True)) | (Block.id.in_(kept)),
                )
                .order_by(Block.ordinal)
            )
        )

        wanted: set[uuid.UUID] = {uuid.UUID(row["revision_id"]) for row in kept.values()}
        wanted.update(b.current_revision_id for b in blocks if b.current_revision_id is not None)
        texts = {
            row.id: row.text
            for row in await self._session.scalars(
                self.scoped(TranslationRevision).where(TranslationRevision.id.in_(wanted))
            )
        }
        prefix = str(release.manifest["chapter_code"])
        found: list[WorkingChange] = []

        for block in blocks:
            entry = kept.get(block.id)
            frozen = uuid.UUID(entry["revision_id"]) if entry is not None else None
            current = block.current_revision_id if block.active else None
            if frozen == current:
                continue

            final_text = texts.get(frozen) if frozen is not None else None
            working_text = texts.get(current) if current is not None else None
            found.append(
                WorkingChange(
                    block_id=block.id,
                    code=f"{prefix}-{block.code}",
                    final_text=final_text,
                    working_text=working_text,
                    changes=compare(final_text or "", working_text or ""),
                )
            )

        return found

    # ── внутреннее ──

    async def _manifest(
        self, chapter: Chapter, master: ChapterMaster, terminology: Any
    ) -> dict[str, Any]:
        blocks = list(
            await self._session.scalars(
                self.scoped(Block)
                .where(Block.chapter_id == chapter.id, Block.active.is_(True))
                .order_by(Block.ordinal)
            )
        )
        ids = [b.current_revision_id for b in blocks if b.current_revision_id is not None]
        revisions = {
            row.id: row
            for row in await self._session.scalars(
                self.scoped(TranslationRevision).where(TranslationRevision.id.in_(ids))
            )
        }
        listing = await ObjectService(self._session, self._context, self._storage).listing(
            master.id
        )

        return {
            "schema": MANIFEST_SCHEMA,
            "book_id": str(chapter.book_id),
            "chapter_id": str(chapter.id),
            "chapter_code": chapter.code,
            "chapter_ordinal": chapter.ordinal,
            "chapter_title": chapter.title,
            "master_id": str(master.id),
            "master_version": master.version,
            "master_checksum": master.checksum,
            "glossary_version_id": str(terminology.id) if terminology is not None else None,
            "blocks": [
                {
                    "id": str(block.id),
                    "code": block.code,
                    "ordinal": block.ordinal,
                    "revision_id": str(block.current_revision_id),
                    "revision_no": revisions[block.current_revision_id].revision_no,  # type: ignore[index]
                    "text_sha256": sha256_text(revisions[block.current_revision_id].text),  # type: ignore[index]
                }
                for block in blocks
            ],
            "objects": [
                {
                    "id": str(item.object.id),
                    "code": item.object.code,
                    "type": item.object.type.value,
                    "checksum": item.object.checksum,
                    "content_hash": content_hash(item.object, own_blocks(item)),
                }
                for item in listing.objects
                if item.object.active
            ],
        }

    async def _view(self, release: ChapterRelease, current_hash: str) -> ReleaseView:
        return ReleaseView(
            release=release,
            creator=await self._email(release.created_by_id),
            approver=await self._email(release.approved_by_id),
            working_differs=release.revision_set_hash != current_hash,
        )

    async def _email(self, user_id: uuid.UUID | None) -> str | None:
        if user_id is None:
            return None

        user = await self._session.get(User, user_id)

        return user.email if user is not None else None

    def _audit(self, kind: str, release: ChapterRelease) -> None:
        AuditService(self._session, self._context).record(
            kind=kind,
            subject_type="chapter_release",
            subject_id=release.id,
            payload={
                "code": release.code,
                "chapter_id": str(release.chapter_id),
                "manifest_hash": release.manifest_hash,
            },
        )

    async def _release(self, release_id: uuid.UUID) -> ChapterRelease:
        release = await self._session.scalar(
            self.scoped(ChapterRelease).where(ChapterRelease.id == release_id)
        )
        if release is None:
            raise NotFoundError("Такой версии главы нет")

        return release

    async def _locked(self, release_id: uuid.UUID) -> ChapterRelease:
        release = await self._session.scalar(
            self.scoped(ChapterRelease).where(ChapterRelease.id == release_id).with_for_update()
        )
        if release is None:
            raise NotFoundError("Такой версии главы нет")

        return release

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _book_code(self, chapter: Chapter) -> str:
        book = await self._session.get_one(BookEdition, chapter.book_id)

        return book.code

    async def _master(self, chapter_id: uuid.UUID) -> ChapterMaster | None:
        found: ChapterMaster | None = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )

        return found

    async def _job_is_live(self, chapter_id: uuid.UUID) -> bool:
        found = await self._session.scalar(
            self.scoped(TranslationJob)
            .where(TranslationJob.chapter_id == chapter_id, TranslationJob.state.in_(LIVE))
            .limit(1)
        )

        return found is not None

    async def _pending_regression(self, chapter_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(RegressionItem)
            .join(RegressionRun, RegressionRun.id == RegressionItem.run_id)
            .join(Issue, Issue.id == RegressionRun.issue_id)
            .where(
                RegressionRun.organization_id == self.organization_id,
                RegressionRun.status == RegressionStatus.OPEN,
                RegressionItem.required.is_(True),
                RegressionItem.decision == RegressionDecision.PENDING,
                Issue.chapter_id == chapter_id,
            )
        )

        return int(count or 0)

    async def _completed(self, chapter_id: uuid.UUID, kind: ReviewKind) -> ReviewRun | None:
        found: ReviewRun | None = await self._session.scalar(
            self.scoped(ReviewRun)
            .where(
                ReviewRun.chapter_id == chapter_id,
                ReviewRun.kind == kind,
                ReviewRun.status == ReviewStatus.COMPLETED,
            )
            .order_by(ReviewRun.completed_at.desc())
            .limit(1)
        )

        return found

    async def _coverage_gap(self, run: ReviewRun) -> bool:
        view = await ReviewService(self._session, self._context, self._storage).get(run.id)

        return not view.progress.complete

    async def _pairs(self, chapter_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
        rows = await self._session.execute(
            select(Block.id, Block.current_revision_id).where(
                Block.organization_id == self.organization_id,
                Block.chapter_id == chapter_id,
                Block.active.is_(True),
            )
        )

        return [(row[0], row[1]) for row in rows.all()]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_manifest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def _next_version(latest: ChapterRelease | None, *, major: bool) -> tuple[int, int]:
    if latest is None:
        return (1, 0)
    if major:
        return (latest.version_major + 1, 0)

    return (latest.version_major, latest.version_minor + 1)
