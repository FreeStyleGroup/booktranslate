"""Контроль выпуска: PASS только при нуле причин, и это проверяет сервер.

Экран показывает тот же список, по которому решает API, поэтому обойти его нельзя: кнопка на
экране лишь зовёт ту же проверку. Перед PASS файлы читаются из хранилища заново и сверяются с
суммами: подмена файла после аудита должна его остановить.

PASS — отдельная запись: кто, когда, снимок проверки, манифест и суммы файлов. После него выпуск,
его файлы и аудит не меняются, и это держит база.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import BookEdition, BookStatus
from app.models.issue import Issue, IssueSeverity
from app.models.job import LIVE, TranslationJob
from app.models.organization import Role
from app.models.regression import (
    RegressionDecision,
    RegressionItem,
    RegressionRun,
    RegressionStatus,
)
from app.models.release import (
    ArtifactFormat,
    BookRelease,
    BookReleaseStatus,
    ChapterRelease,
    ExportArtifact,
    PageAudit,
    PageStatus,
    ReleasePass,
    ReleaseStatus,
)
from app.models.review import ReviewRun, ReviewStatus
from app.models.workspace import WorkspaceSettings
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, NotFoundError
from app.services.export.base import ExportError, Rendered
from app.services.export.pdf import text_layer
from app.services.export.scan import readable_text, scan
from app.services.issue_status import OPEN
from app.services.publication import PublicationService
from app.services.storage import ObjectStorage

PASSING_ROLES = (Role.ADMIN, Role.MANAGER)

# Сколько замечаний и страниц показывать поимённо: дальше важно только число.
SHOWN = 50

CHECKS = (
    ("chapters_approved", "Все главы утверждены"),
    ("final_compare_current", "Финальная сверка действует"),
    ("no_open_critical", "Нет незакрытых критичных замечаний"),
    ("no_open_major", "Нет незакрытых серьёзных замечаний"),
    ("no_open_minor", "Незначительные замечания по правилам пространства"),
    ("no_pending_regression", "Регрессия решена"),
    ("artifacts_current", "Файлы DOCX и PDF собраны из этого манифеста"),
    ("pages_audited", "У каждой страницы PDF есть результат аудита"),
    ("reader_scan_clean", "В файлах нет служебных кодов и заметок"),
)


@dataclass(frozen=True, slots=True)
class GateBlocker:
    check: str
    code: str
    message: str
    count: int | None = None
    chapter_id: uuid.UUID | None = None
    issue_id: uuid.UUID | None = None
    page_no: int | None = None


@dataclass(slots=True)
class GateResult:
    release: BookRelease
    blockers: list[GateBlocker] = field(default_factory=list)
    passed: ReleasePass | None = None

    @property
    def ready(self) -> bool:
        return not self.blockers

    def snapshot(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": [
                {"code": code, "passed": not any(row.check == code for row in self.blockers)}
                for code, _ in CHECKS
            ],
            "blockers": [
                {"check": row.check, "code": row.code, "message": row.message, "count": row.count}
                for row in self.blockers
            ],
        }


class ReleaseGateService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def check(self, release_id: uuid.UUID) -> GateResult:
        release = await self._release(release_id)
        result = GateResult(release=release)
        result.passed = await self._session.scalar(
            self.scoped(ReleasePass).where(ReleasePass.release_id == release.id)
        )

        await self._check_chapters(result)
        await self._check_issues(result)
        await self._check_regression(result)
        await self._check_artifacts(result)

        return result

    async def pass_release(self, release_id: uuid.UUID, *, automatic: bool = False) -> GateResult:
        """Выставить PASS. Те же проверки, что на экране, плюс сверка файлов в хранилище."""
        self._context.require(*PASSING_ROLES)

        release = await self._session.scalar(
            self.scoped(BookRelease).where(BookRelease.id == release_id).with_for_update()
        )
        if release is None:
            raise NotFoundError("Такого выпуска нет")
        if release.status is BookReleaseStatus.PASSED:
            raise ConflictError(f"{release.code} уже прошёл контроль")

        gate = await self.check(release.id)
        if not gate.ready:
            raise ConflictError(
                "Контроль не пройден: " + "; ".join(row.message for row in gate.blockers[:10])
            )

        artifacts = await self._current(release.id)
        await self._verify_files(release, artifacts)

        # Подтверждение честно говорит о своём происхождении, кто бы ни нажал кнопку.
        automatic = automatic or await self._was_automatic(release, artifacts)

        record = ReleasePass(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            release_id=release.id,
            actor_id=self._context.user.id,
            manifest_hash=release.manifest_hash,
            gate_snapshot={**gate.snapshot(), "automatic": automatic},
            artifacts=[
                {
                    "id": str(row.id),
                    "format": row.format.value,
                    "checksum": row.checksum,
                    "renderer_version": row.renderer_version,
                    "page_count": row.page_count,
                }
                for row in artifacts
            ],
            created_at=datetime.now(UTC),
        )

        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError(f"{release.code} уже прошёл контроль") from error

        release.status = BookReleaseStatus.PASSED
        book = await self._session.get_one(BookEdition, release.book_id)
        book.status = BookStatus.RELEASED
        AuditService(self._session, self._context).record(
            kind="book_release.passed",
            subject_type="book_release",
            subject_id=release.id,
            payload={
                "code": release.code,
                "manifest_hash": release.manifest_hash,
                "artifacts": record.artifacts,
                "automatic": automatic,
            },
        )
        await self._session.commit()

        return await self.check(release.id)

    # ── проверки ──

    async def _check_chapters(self, result: GateResult) -> None:
        release = result.release
        ids = [uuid.UUID(row["release_id"]) for row in release.manifest["chapters"]]
        rows = list(
            await self._session.scalars(
                self.scoped(ChapterRelease).where(ChapterRelease.id.in_(ids))
            )
        )

        for row in rows:
            if row.status is not ReleaseStatus.APPROVED:
                result.blockers.append(
                    GateBlocker(
                        "chapters_approved",
                        "chapter_not_approved",
                        f"Версия {row.code} не утверждена",
                        chapter_id=row.chapter_id,
                    )
                )

        runs = {
            run.id: run
            for run in await self._session.scalars(
                self.scoped(ReviewRun).where(
                    ReviewRun.id.in_([row.final_compare_id for row in rows])
                )
            )
        }
        for row in rows:
            run = runs.get(row.final_compare_id)
            if (
                run is None
                or run.status is not ReviewStatus.COMPLETED
                or run.completed_revision_set_hash != row.revision_set_hash
            ):
                result.blockers.append(
                    GateBlocker(
                        "final_compare_current",
                        "final_compare_stale",
                        f"Сверка версии {row.code} была про другой текст",
                        chapter_id=row.chapter_id,
                    )
                )

    async def _check_issues(self, result: GateResult) -> None:
        book_id = result.release.book_id
        policy = await self._session.scalar(
            select(WorkspaceSettings.minor_blocks_release).where(
                WorkspaceSettings.organization_id == self.organization_id
            )
        )
        wanted = [
            (IssueSeverity.CRITICAL, "no_open_critical", "open_critical", "Критичное"),
            (IssueSeverity.MAJOR, "no_open_major", "open_major", "Серьёзное"),
        ]
        if policy:
            wanted.append((IssueSeverity.MINOR, "no_open_minor", "open_minor", "Незначительное"))

        for severity, check, code, word in wanted:
            rows = list(
                await self._session.scalars(
                    self.scoped(Issue)
                    .where(
                        Issue.book_id == book_id,
                        Issue.severity == severity,
                        Issue.status.in_(OPEN),
                        Issue.archived_at.is_(None),
                    )
                    .order_by(Issue.code)
                    .limit(SHOWN)
                )
            )
            for issue in rows:
                result.blockers.append(
                    GateBlocker(
                        check,
                        code,
                        f"{word} замечание {issue.code} не закрыто",
                        chapter_id=issue.chapter_id,
                        issue_id=issue.id,
                    )
                )

    async def _check_regression(self, result: GateResult) -> None:
        """Обязательное место регрессии держит выпуск, откуда бы ни пришло исправление."""
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
                Issue.book_id == result.release.book_id,
            )
        )
        if count:
            result.blockers.append(
                GateBlocker(
                    "no_pending_regression",
                    "regression_pending",
                    f"Не решено мест в регрессии: {count}",
                    count=int(count),
                )
            )

    async def _was_automatic(self, release: BookRelease, artifacts: list[ExportArtifact]) -> bool:
        ids = [uuid.UUID(row["release_id"]) for row in release.manifest["chapters"]]
        chapters = await self._session.scalars(
            self.scoped(ChapterRelease).where(ChapterRelease.id.in_(ids))
        )
        if any(row.manifest.get("automatic") for row in chapters):
            return True

        pdf = next((row for row in artifacts if row.format is ArtifactFormat.PDF), None)
        if pdf is None:
            return False

        found = await self._first_page(pdf.id, PageStatus.AUTO_PASS)

        return found is not None

    async def _check_artifacts(self, result: GateResult) -> None:
        release = result.release
        job = await self._session.scalar(
            self.scoped(TranslationJob)
            .where(TranslationJob.book_release_id == release.id, TranslationJob.state.in_(LIVE))
            .limit(1)
        )
        if job is not None:
            result.blockers.append(
                GateBlocker("artifacts_current", "render_running", "Файлы сейчас собираются")
            )

        current = {row.format: row for row in await self._current(release.id)}

        # Файл сохраняется только чистым, поэтому собранный файл и есть проверенный. Перед самим
        # подтверждением файлы перечитываются и проверяются ещё раз.
        if set(current) != set(ArtifactFormat):
            result.blockers.append(
                GateBlocker(
                    "reader_scan_clean",
                    "scan_missing",
                    "Файлы ещё не проверены на служебное: их нет",
                )
            )

        for kind in ArtifactFormat:
            artifact = current.get(kind)
            if artifact is None:
                result.blockers.append(
                    GateBlocker(
                        "artifacts_current",
                        "artifact_missing",
                        f"Файл {kind.value.upper()} не собран",
                    )
                )
            elif artifact.manifest_hash != release.manifest_hash:
                result.blockers.append(
                    GateBlocker(
                        "artifacts_current",
                        "artifact_stale",
                        f"Файл {kind.value.upper()} собран из другого манифеста",
                    )
                )

        pdf = current.get(ArtifactFormat.PDF)
        if pdf is None:
            result.blockers.append(
                GateBlocker("pages_audited", "pages_unreviewed", "Нечего проверять: нет PDF")
            )
            return

        counts = {
            row[0]: row[1]
            for row in (
                await self._session.execute(
                    select(PageAudit.status, func.count())
                    .where(
                        PageAudit.organization_id == self.organization_id,
                        PageAudit.artifact_id == pdf.id,
                    )
                    .group_by(PageAudit.status)
                )
            ).all()
        }
        waiting = counts.get(PageStatus.UNREVIEWED, 0)
        if waiting:
            result.blockers.append(
                GateBlocker(
                    "pages_audited",
                    "pages_unreviewed",
                    f"Не проверено страниц: {waiting}",
                    count=waiting,
                    page_no=await self._first_page(pdf.id, PageStatus.UNREVIEWED),
                )
            )

        faulty = counts.get(PageStatus.ISSUE, 0)
        if faulty:
            result.blockers.append(
                GateBlocker(
                    "pages_audited",
                    "page_issue",
                    f"Страниц с ошибкой: {faulty}",
                    count=faulty,
                    page_no=await self._first_page(pdf.id, PageStatus.ISSUE),
                )
            )

    async def _verify_files(self, release: BookRelease, artifacts: list[ExportArtifact]) -> None:
        """Файлы в хранилище те самые и чистые: аудит был именно про них."""
        publication = PublicationService(self._session, self._context, self._storage)
        ids = [uuid.UUID(row["release_id"]) for row in release.manifest["chapters"]]
        rows = {
            row.id: row
            for row in await self._session.scalars(
                self.scoped(ChapterRelease).where(ChapterRelease.id.in_(ids))
            )
        }
        view = await publication.view([rows[item] for item in ids])

        for artifact in artifacts:
            parts = [chunk async for chunk in self._storage.stream(artifact.storage_key)]
            content = b"".join(parts)

            if hashlib.sha256(content).hexdigest() != artifact.checksum:
                raise ConflictError(
                    f"Файл {artifact.format.value.upper()} в хранилище не совпадает с суммой: "
                    "соберите файлы заново"
                )

            try:
                text = (
                    await asyncio.to_thread(text_layer, content)
                    if artifact.format is ArtifactFormat.PDF
                    else readable_text(Rendered(content, "", ".docx"))
                )
            except ExportError as error:
                raise ConflictError(str(error)) from error

            found = scan(text, source_texts=view.source_texts, notes=view.notes)
            if found:
                raise ConflictError(
                    f"В файле {artifact.format.value.upper()} нашлось служебное: "
                    + "; ".join(found[:10])
                )

    async def _current(self, release_id: uuid.UUID) -> list[ExportArtifact]:
        rows = await self._session.scalars(
            self.scoped(ExportArtifact)
            .where(ExportArtifact.release_id == release_id, ExportArtifact.superseded_at.is_(None))
            .order_by(ExportArtifact.format)
        )

        return list(rows)

    async def _first_page(self, artifact_id: uuid.UUID, status: PageStatus) -> int | None:
        found: int | None = await self._session.scalar(
            select(func.min(PageAudit.page_no)).where(
                PageAudit.organization_id == self.organization_id,
                PageAudit.artifact_id == artifact_id,
                PageAudit.status == status,
            )
        )

        return found

    async def _release(self, release_id: uuid.UUID) -> BookRelease:
        release = await self._session.scalar(
            self.scoped(BookRelease)
            .where(BookRelease.id == release_id)
            .execution_options(populate_existing=True)
        )
        if release is None:
            raise NotFoundError("Такого выпуска нет")

        return release
