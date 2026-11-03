"""Проверки главы: запуск, состояние, очередь находок.

Формальная отметка и смысловая сверка — разные индикаторы и считаются раздельно: одна не заменяет
другую. Формальная действует только для нынешней версии правил, а смысловая — для редакции, какой бы
версией промпта её ни проверяли: платить второй раз за тот же текст незачем.

Запуск одновременно с переводом той же главы невозможен: живое задание на главу одно, и пока
текст меняется, проверять его бессмысленно.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError

from app.models.block import Block
from app.models.chapter import Chapter
from app.models.issue import Issue, IssueCategory, IssueSeverity, IssueStatus
from app.models.job import LIVE, JobKind, JobState, TranslationJob
from app.models.master import ChapterMaster
from app.models.organization import Role
from app.models.qa import FindingDisposition, QAFinding, QAKind, QARun, QAScope, RevisionCheck
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.canonical import revision_set_hash
from app.services.checks import CHECK_PROFILE_VERSION
from app.services.errors import ConflictError, NotFoundError
from app.services.providers import semantic_info
from app.services.workspace import model_for, semantic_scope_for

# Формальная проверка бесплатна: её запускает всякий, кто работает с текстом.
CHECKING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER)
# Смысловая сверка стоит денег: переводчик сам себе её не назначает.
SEMANTIC_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER)


@dataclass(frozen=True, slots=True)
class RunView:
    run: QARun
    job: TranslationJob | None


@dataclass(frozen=True, slots=True)
class ChapterChecks:
    """Что известно о проверках главы сейчас."""

    total: int
    translated: int
    formal: int
    semantic: int
    revision_set_hash: str
    latest_formal: RunView | None
    latest_semantic: RunView | None
    live: RunView | None
    semantic_scope: QAScope


@dataclass(slots=True)
class FindingRow:
    finding: QAFinding
    block_code: str
    chapter_id: uuid.UUID
    book_id: uuid.UUID
    issue_code: str | None
    issue_status: IssueStatus | None


@dataclass(slots=True)
class FindingPage:
    total: int
    items: list[FindingRow]


class QAService(TenantService):
    async def start(self, chapter_id: uuid.UUID, kind: QAKind) -> RunView:
        self._context.require(*(SEMANTIC_ROLES if kind is QAKind.SEMANTIC else CHECKING_ROLES))

        chapter = await self._chapter(chapter_id)
        master = await self._master(chapter.id)
        pairs = await self._pairs(chapter.id)
        translated = sum(1 for _, revision in pairs if revision is not None)

        if translated == 0:
            raise ConflictError("Проверять нечего: в главе нет переведённых блоков")

        info = semantic_info(await model_for(self._session, self.organization_id))
        scope = (
            await semantic_scope_for(self._session, self.organization_id)
            if kind is QAKind.SEMANTIC
            else QAScope.ALL
        )

        run = QARun(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            master_id=master.id,
            kind=kind,
            scope=scope,
            check_profile_version=(
                CHECK_PROFILE_VERSION if kind is QAKind.DETERMINISTIC else info.prompt_version
            ),
            revision_set_hash=revision_set_hash(pairs),
            provider=info.provider if kind is QAKind.SEMANTIC else None,
            model=info.model if kind is QAKind.SEMANTIC else None,
            requested_by_id=self._context.user.id,
            blocks_total=translated,
            blocks_checked=0,
            blocks_untranslated=len(pairs) - translated,
            findings_total=0,
            issues_created=0,
            cursor=-1,
            rejections=[],
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cache_write_tokens=0,
        )
        job = TranslationJob(
            organization_id=self.organization_id,
            kind=JobKind.QA,
            chapter_id=chapter.id,
            qa_run_id=run.id,
            state=JobState.WAITING,
            requested_by_id=self._context.user.id,
            items_total=translated,
        )

        AuditService(self._session, self._context).record(
            kind="qa.started",
            subject_type="qa_run",
            subject_id=run.id,
            payload={
                "chapter_id": str(chapter.id),
                "chapter_code": chapter.code,
                "kind": kind.value,
                "scope": scope.value,
                "revision_set_hash": run.revision_set_hash,
                "check_profile_version": run.check_profile_version,
            },
        )

        self._session.add(run)
        await self._session.flush()
        self._session.add(job)

        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("По этой главе уже идёт работа: дождитесь её конца") from error

        await self._session.refresh(run)
        await self._session.refresh(job)

        return RunView(run=run, job=job)

    async def state(self, chapter_id: uuid.UUID) -> ChapterChecks:
        chapter = await self._chapter(chapter_id)
        pairs = await self._pairs(chapter.id)
        current = [revision for _, revision in pairs if revision is not None]
        covered = await self._coverage(current)

        return ChapterChecks(
            total=len(pairs),
            translated=len(current),
            formal=sum(1 for revision in current if covered.get(revision, (False, False))[0]),
            semantic=sum(1 for revision in current if covered.get(revision, (False, False))[1]),
            revision_set_hash=revision_set_hash(pairs),
            latest_formal=await self._latest(chapter.id, QAKind.DETERMINISTIC),
            latest_semantic=await self._latest(chapter.id, QAKind.SEMANTIC),
            live=await self._live(chapter.id),
            semantic_scope=await semantic_scope_for(self._session, self.organization_id),
        )

    async def coverage_of(
        self, revision_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[bool, bool]]:
        """Отметки редакций: (формально проверено, смысловая сверка выполнена)."""
        return await self._coverage(revision_ids)

    async def runs(self, *, chapter_id: uuid.UUID | None = None, limit: int = 20) -> list[RunView]:
        statement = self.scoped(QARun)

        if chapter_id is not None:
            statement = statement.where(QARun.chapter_id == chapter_id)

        rows = list(
            await self._session.scalars(statement.order_by(QARun.created_at.desc()).limit(limit))
        )
        jobs = await self._jobs([row.id for row in rows])

        return [RunView(run=row, job=jobs.get(row.id)) for row in rows]

    async def findings(
        self,
        *,
        book_id: uuid.UUID | None = None,
        chapter_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        kind: QAKind | None = None,
        check: str | None = None,
        severity: IssueSeverity | None = None,
        category: IssueCategory | None = None,
        disposition: FindingDisposition | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> FindingPage:
        """Очередь проверок: находки новых прогонов сверху, тяжёлые раньше."""
        statement: Select[tuple[QAFinding]] = self.scoped(QAFinding)

        if book_id is not None:
            statement = statement.join(Chapter, Chapter.id == QAFinding.chapter_id).where(
                Chapter.book_id == book_id
            )
        if chapter_id is not None:
            statement = statement.where(QAFinding.chapter_id == chapter_id)
        if run_id is not None:
            statement = statement.where(QAFinding.qa_run_id == run_id)
        if kind is not None:
            statement = statement.where(QAFinding.kind == kind)
        if check is not None:
            statement = statement.where(QAFinding.check_name == check)
        if severity is not None:
            statement = statement.where(QAFinding.severity == severity)
        if category is not None:
            statement = statement.where(QAFinding.category == category)
        if disposition is not None:
            statement = statement.where(QAFinding.disposition == disposition)

        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = list(
            await self._session.scalars(
                statement.order_by(QAFinding.created_at.desc(), QAFinding.severity, QAFinding.id)
                .limit(limit)
                .offset(offset)
            )
        )

        return FindingPage(total=int(total or 0), items=await self._finding_rows(rows))

    # ── внутреннее ──

    async def _finding_rows(self, rows: Sequence[QAFinding]) -> list[FindingRow]:
        if not rows:
            return []

        blocks = {
            block.id: block
            for block in await self._session.scalars(
                self.scoped(Block).where(Block.id.in_({row.block_id for row in rows}))
            )
        }
        chapters = {
            chapter.id: chapter
            for chapter in await self._session.scalars(
                self.scoped(Chapter).where(Chapter.id.in_({row.chapter_id for row in rows}))
            )
        }
        issue_ids = {row.issue_id for row in rows if row.issue_id is not None}
        issues = (
            {
                issue.id: issue
                for issue in await self._session.scalars(
                    self.scoped(Issue).where(Issue.id.in_(issue_ids))
                )
            }
            if issue_ids
            else {}
        )

        result = []
        for row in rows:
            chapter = chapters[row.chapter_id]
            issue = issues.get(row.issue_id) if row.issue_id is not None else None
            code = blocks[row.block_id].code

            result.append(
                FindingRow(
                    finding=row,
                    block_code=f"{chapter.code}-{code}" if chapter.code is not None else code,
                    chapter_id=chapter.id,
                    book_id=chapter.book_id,
                    issue_code=issue.code if issue is not None else None,
                    issue_status=issue.status if issue is not None else None,
                )
            )

        return result

    async def _coverage(
        self, revision_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[bool, bool]]:
        if not revision_ids:
            return {}

        rows = await self._session.execute(
            select(
                RevisionCheck.revision_id, RevisionCheck.kind, RevisionCheck.check_profile_version
            ).where(
                RevisionCheck.organization_id == self.organization_id,
                RevisionCheck.revision_id.in_(revision_ids),
            )
        )

        covered: dict[uuid.UUID, tuple[bool, bool]] = {}
        for revision, kind, version in rows.all():
            formal, semantic = covered.get(revision, (False, False))

            if kind is QAKind.DETERMINISTIC and version == CHECK_PROFILE_VERSION:
                formal = True
            if kind is QAKind.SEMANTIC:
                semantic = True

            covered[revision] = (formal, semantic)

        return covered

    async def _pairs(self, chapter_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
        rows = await self._session.execute(
            select(Block.id, Block.current_revision_id).where(
                Block.organization_id == self.organization_id,
                Block.chapter_id == chapter_id,
                Block.active.is_(True),
            )
        )

        return [(row[0], row[1]) for row in rows.all()]

    async def _latest(self, chapter_id: uuid.UUID, kind: QAKind) -> RunView | None:
        run = await self._session.scalar(
            self.scoped(QARun)
            .where(QARun.chapter_id == chapter_id, QARun.kind == kind)
            .order_by(QARun.created_at.desc())
            .limit(1)
        )
        if run is None:
            return None

        jobs = await self._jobs([run.id])

        return RunView(run=run, job=jobs.get(run.id))

    async def _live(self, chapter_id: uuid.UUID) -> RunView | None:
        job = await self._session.scalar(
            self.scoped(TranslationJob).where(
                TranslationJob.chapter_id == chapter_id,
                TranslationJob.kind == JobKind.QA,
                TranslationJob.state.in_(list(LIVE)),
            )
        )
        if job is None:
            return None

        run = await self._session.get(QARun, job.qa_run_id)

        return RunView(run=run, job=job) if run is not None else None

    async def _jobs(self, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, TranslationJob]:
        if not run_ids:
            return {}

        rows = await self._session.scalars(
            self.scoped(TranslationJob).where(TranslationJob.qa_run_id.in_(run_ids))
        )

        return {row.qa_run_id: row for row in rows if row.qa_run_id is not None}

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _master(self, chapter_id: uuid.UUID) -> ChapterMaster:
        master = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )
        if master is None:
            raise ConflictError("У главы нет мастера: проверять нечего")

        return master
