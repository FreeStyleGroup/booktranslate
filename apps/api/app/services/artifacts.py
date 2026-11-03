"""Файлы выпуска и постраничный аудит PDF.

DOCX и PDF собираются из одного манифеста и лежат с суммами: что проверили, то и уйдёт читателю.
Пересборка заводит новые файлы, а прежний аудит становится устаревшим: он был про другой файл.

Страница с ошибкой заводит обычное замечание категории «вёрстка». Замечанию нужен блок, поэтому при
сборке запоминается, какие блоки стоят на какой странице: страница сама находит свой адрес.
"""

import asyncio
import hashlib
import io
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.issue import Issue, IssueCategory, IssueSeverity
from app.models.job import JobKind, JobState, TranslationJob
from app.models.organization import Role
from app.models.release import (
    ArtifactFormat,
    BookRelease,
    BookReleaseStatus,
    ExportArtifact,
    PageAudit,
    PageStatus,
)
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.export import ExportFormat
from app.services.export.pdf import (
    STUB_RENDERER,
    RenderedPdf,
    page_png,
    render_isolated,
    render_stub,
)
from app.services.issue_attachments import IssueAttachments
from app.services.issue_status import DECIDED
from app.services.issues import IssueService
from app.services.publication import PublicationService
from app.services.storage import ObjectStorage

RENDERING_ROLES = (Role.ADMIN, Role.MANAGER)
AUDITING_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER)

MEDIA_TYPES = {
    ArtifactFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ArtifactFormat.PDF: "application/pdf",
}
SUFFIXES = {ArtifactFormat.DOCX: ".docx", ArtifactFormat.PDF: ".pdf"}


@dataclass(frozen=True, slots=True)
class ReleaseFiles:
    artifacts: list[ExportArtifact]
    # Прежние файлы: показываются как устаревшие.
    previous: list[ExportArtifact]
    job: TranslationJob | None


class ArtifactService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def request_render(self, release_id: uuid.UUID) -> TranslationJob:
        """Поставить сборку файлов в очередь: книга собирается минуты, запросу столько не ждать."""
        self._context.require(*RENDERING_ROLES)

        release = await self._release(release_id)
        if release.status is BookReleaseStatus.PASSED:
            raise ConflictError(f"{release.code} прошёл контроль и не пересобирается")

        job = TranslationJob(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            kind=JobKind.RENDER,
            book_release_id=release.id,
            state=JobState.WAITING,
            requested_by_id=self._context.user.id,
            items_total=len(ArtifactFormat),
        )

        try:
            async with self._session.begin_nested():
                self._session.add(job)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Файлы этого выпуска уже собираются") from error

        AuditService(self._session, self._context).record(
            kind="book_release.render_requested",
            subject_type="book_release",
            subject_id=release.id,
            payload={"code": release.code},
        )
        await self._session.commit()

        return await self._job(job.id)

    async def files(self, release_id: uuid.UUID) -> ReleaseFiles:
        release = await self._release(release_id)
        rows = list(
            await self._session.scalars(
                self.scoped(ExportArtifact)
                .where(ExportArtifact.release_id == release.id)
                .order_by(ExportArtifact.created_at.desc(), ExportArtifact.format)
            )
        )
        job = await self._session.scalar(
            self.scoped(TranslationJob)
            .where(TranslationJob.book_release_id == release.id)
            .order_by(TranslationJob.created_at.desc())
            .limit(1)
        )

        return ReleaseFiles(
            artifacts=[row for row in rows if row.superseded_at is None],
            previous=[row for row in rows if row.superseded_at is not None],
            job=job,
        )

    async def render(
        self, release_id: uuid.UUID, *, tick: Callable[[], Awaitable[None]] | None = None
    ) -> int:
        """Собрать DOCX и PDF, проверить и заменить прежние. Выполняет рабочий процесс."""
        release = await self._release(release_id)
        if release.status is BookReleaseStatus.PASSED:
            raise ConflictError(f"{release.code} прошёл контроль и не пересобирается")

        publication = PublicationService(self._session, self._context, self._storage)

        docx = await publication.render_book_release(release, export_format=ExportFormat.DOCX)
        document, view = await publication.pdf_document(release)

        pdf = (
            render_stub(document)
            if get_settings().pdf_engine == STUB_RENDERER
            else await render_isolated(document, tick=tick)
        )
        await publication.check_pdf(pdf.content, view)

        now = datetime.now(UTC)
        await self._session.execute(
            update(PageAudit)
            .where(
                PageAudit.organization_id == self.organization_id,
                PageAudit.artifact_id.in_(
                    select(ExportArtifact.id).where(
                        ExportArtifact.release_id == release.id,
                        ExportArtifact.superseded_at.is_(None),
                    )
                ),
            )
            .values(status=PageStatus.STALE)
        )
        await self._session.execute(
            update(ExportArtifact)
            .where(
                ExportArtifact.organization_id == self.organization_id,
                ExportArtifact.release_id == release.id,
                ExportArtifact.superseded_at.is_(None),
            )
            .values(superseded_at=now)
        )
        await self._session.flush()

        await self._store(release, ArtifactFormat.DOCX, docx.rendered.content, "python-docx")
        artifact = await self._store(release, ArtifactFormat.PDF, pdf.content, pdf.renderer, pdf)
        await self._session.flush()

        self._session.add_all(
            PageAudit(
                organization_id=self.organization_id,
                artifact_id=artifact.id,
                page_no=number,
                status=PageStatus.UNREVIEWED,
            )
            for number in range(1, len(pdf.page_map) + 1)
        )

        AuditService(self._session, self._context).record(
            kind="book_release.rendered",
            subject_type="book_release",
            subject_id=release.id,
            payload={
                "code": release.code,
                "manifest_hash": release.manifest_hash,
                "pdf_sha256": artifact.checksum,
                "pages": len(pdf.page_map),
                "renderer": pdf.renderer,
            },
        )
        await self._session.commit()

        return len(ArtifactFormat)

    async def artifact(self, artifact_id: uuid.UUID) -> ExportArtifact:
        found = await self._session.scalar(
            self.scoped(ExportArtifact).where(ExportArtifact.id == artifact_id)
        )
        if found is None:
            raise NotFoundError("Такого файла нет")

        return found

    async def read(self, artifact: ExportArtifact) -> bytes:
        parts = [chunk async for chunk in self._storage.stream(artifact.storage_key)]

        return b"".join(parts)

    def filename(self, release: BookRelease, artifact: ExportArtifact) -> str:
        return f"{release.code}{SUFFIXES[artifact.format]}"

    async def release_of(self, artifact: ExportArtifact) -> BookRelease:
        return await self._release(artifact.release_id)

    async def pages(self, artifact_id: uuid.UUID) -> list[PageAudit]:
        artifact = await self.artifact(artifact_id)
        rows = await self._session.scalars(
            self.scoped(PageAudit)
            .where(PageAudit.artifact_id == artifact.id)
            .order_by(PageAudit.page_no)
        )

        return list(rows)

    async def page_image(self, artifact_id: uuid.UUID, page_no: int) -> bytes:
        artifact = await self._pdf(artifact_id)
        if not 1 <= page_no <= (artifact.page_count or 0):
            raise NotFoundError("Такой страницы нет")

        content = await self.read(artifact)

        return await asyncio.to_thread(page_png, content, page_no)

    async def mark_page(self, artifact_id: uuid.UUID, page_no: int) -> PageAudit:
        """Страница верна. Страницу с незакрытым замечанием так не отметить."""
        self._context.require(*AUDITING_ROLES)

        artifact = await self._pdf(artifact_id)
        audit = await self._page(artifact, page_no)

        if audit.issue_id is not None:
            issue = await self._session.get(Issue, audit.issue_id)
            if issue is not None and issue.status not in DECIDED:
                raise ConflictError(f"На этой странице открыто замечание {issue.code}")

        audit.status = PageStatus.PASS
        audit.reviewer_id = self._context.user.id
        audit.checked_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(audit)

        return audit

    async def register_page_issue(
        self, artifact_id: uuid.UUID, page_no: int, *, severity: IssueSeverity, description: str
    ) -> tuple[PageAudit, Issue]:
        """Ошибка вёрстки на странице: замечание со снимком страницы."""
        self._context.require(*AUDITING_ROLES)

        artifact = await self._pdf(artifact_id)
        audit = await self._page(artifact, page_no)
        block_id = self._anchor(artifact, page_no)
        if block_id is None:
            raise ConflictError("На файле нет ни одного блока: замечание не к чему привязать")

        text = description.strip()
        if not text:
            raise InvalidInputError("Опишите ошибку")

        issues = IssueService(self._session, self._context, self._storage)
        issue, _ = await issues.file(
            block_id=block_id,
            object_id=None,
            category=IssueCategory.LAYOUT,
            severity=severity,
            description=f"Страница {page_no} файла PDF: {text}",
        )

        audit.status = PageStatus.ISSUE
        audit.issue_id = issue.id
        audit.reviewer_id = self._context.user.id
        audit.checked_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(audit)
        await self._session.refresh(issue)

        png = await asyncio.to_thread(page_png, await self.read(artifact), page_no)
        await IssueAttachments(self._session, self._context, self._storage).accept(
            issue.id,
            file=UploadFile(file=io.BytesIO(png), filename=f"page-{page_no}.png"),
            filename=f"page-{page_no}.png",
        )

        return audit, issue

    # ── внутреннее ──

    def _anchor(self, artifact: ExportArtifact, page_no: int) -> uuid.UUID | None:
        """Блок этой страницы; если на ней их нет — ближайший выше, иначе первый после."""
        pages = artifact.page_map or []
        order = [*range(page_no - 1, -1, -1), *range(page_no, len(pages))]

        for index in order:
            if index < len(pages) and pages[index]:
                return uuid.UUID(pages[index][0])

        return None

    async def _store(
        self,
        release: BookRelease,
        kind: ArtifactFormat,
        content: bytes,
        renderer: str,
        pdf: RenderedPdf | None = None,
    ) -> ExportArtifact:
        digest = hashlib.sha256(content).hexdigest()
        key = f"{self.organization_id}/releases/{release.id}/{uuid.uuid4().hex}{SUFFIXES[kind]}"
        descriptor, name = tempfile.mkstemp(prefix="booktranslate-artifact-")
        path = Path(name)

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
            await self._storage.put(key, path)
        finally:
            path.unlink(missing_ok=True)

        artifact = ExportArtifact(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            release_id=release.id,
            format=kind,
            storage_key=key,
            checksum=digest,
            size=len(content),
            renderer_version=renderer,
            manifest_hash=release.manifest_hash,
            page_count=len(pdf.page_map) if pdf is not None else None,
            page_map=pdf.page_map if pdf is not None else None,
            created_at=datetime.now(UTC),
        )
        self._session.add(artifact)

        return artifact

    async def _pdf(self, artifact_id: uuid.UUID) -> ExportArtifact:
        artifact = await self.artifact(artifact_id)
        if artifact.format is not ArtifactFormat.PDF:
            raise NotFoundError("У этого файла нет страниц")

        return artifact

    async def _page(self, artifact: ExportArtifact, page_no: int) -> PageAudit:
        if artifact.superseded_at is not None:
            raise ConflictError("Этот файл пересобран: проверять нужно новый")

        audit = await self._session.scalar(
            self.scoped(PageAudit)
            .where(PageAudit.artifact_id == artifact.id, PageAudit.page_no == page_no)
            .with_for_update()
        )
        if audit is None:
            raise NotFoundError("Такой страницы нет")

        return audit

    async def _release(self, release_id: uuid.UUID) -> BookRelease:
        release = await self._session.scalar(
            self.scoped(BookRelease).where(BookRelease.id == release_id)
        )
        if release is None:
            raise NotFoundError("Такого выпуска нет")

        return release

    async def _job(self, job_id: uuid.UUID) -> TranslationJob:
        job = await self._session.scalar(
            self.scoped(TranslationJob)
            .where(TranslationJob.id == job_id)
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise NotFoundError("Задание не найдено")

        return job
