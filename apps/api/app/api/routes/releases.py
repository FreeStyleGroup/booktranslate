"""Финальные версии глав и выпуски книги.

Рабочая выгрузка живёт отдельно, в `chapter_translation`. Здесь только то, что опирается на
манифест: читательская версия выдаётся только из утверждённого выпуска."""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.release import BookRelease, ExportArtifact
from app.schemas.chapter_translation import ChangePublic
from app.schemas.release import (
    ArtifactPublic,
    AssemblyItemPublic,
    AssemblyProblemPublic,
    AssemblyPublic,
    AssemblyVersionPublic,
    BlockerPublic,
    BookReleaseCreate,
    BookReleasePublic,
    ChapterReleaseCreate,
    ChapterReleasePublic,
    GateBlockerPublic,
    GateCheckPublic,
    GatePublic,
    ManifestPublic,
    PageAuditPublic,
    PageIssueCreate,
    PageIssueResult,
    ReleaseFilesPublic,
    ReleaseGatePublic,
    TocEntryPublic,
    WorkingChangePublic,
)
from app.services.artifacts import MEDIA_TYPES, ArtifactService, ReleaseFiles
from app.services.assembly import AssemblyService, Plan
from app.services.chapter_releases import ChapterReleaseService, ReleaseView, hash_manifest
from app.services.export import ExportFormat
from app.services.exporting import Export
from app.services.publication import PublicationService
from app.services.release_gate import CHECKS, GateResult, ReleaseGateService

router = APIRouter(tags=["releases"])


def _version(major: int, minor: int) -> str:
    return f"v{major}.{minor}"


def _chapter_release(view: ReleaseView) -> ChapterReleasePublic:
    release = view.release

    return ChapterReleasePublic(
        id=release.id,
        book_id=release.book_id,
        chapter_id=release.chapter_id,
        code=release.code,
        version=_version(release.version_major, release.version_minor),
        status=release.status,
        manifest_hash=release.manifest_hash,
        blocks=len(release.manifest["blocks"]),
        objects=len(release.manifest["objects"]),
        creator=view.creator,
        approver=view.approver,
        approved_at=release.approved_at,
        created_at=release.created_at,
        working_differs=view.working_differs,
    )


def _book_release(release: BookRelease, *, created: bool = True) -> BookReleasePublic:
    return BookReleasePublic(
        id=release.id,
        book_id=release.book_id,
        title=release.manifest["title"],
        code=release.code,
        version=_version(release.version_major, release.version_minor),
        status=release.status,
        manifest_hash=release.manifest_hash,
        chapters=release.manifest["chapters"],
        toc=[TocEntryPublic(**row) for row in release.manifest["toc"]],
        created_at=release.created_at,
        created=created,
    )


def _plan(plan: Plan) -> AssemblyPublic:
    return AssemblyPublic(
        ready=plan.ready,
        items=[
            AssemblyItemPublic(
                chapter_id=item.chapter.id,
                chapter_code=item.chapter.code,
                title=item.chapter.title,
                ordinal=item.chapter.ordinal,
                chosen_id=item.chosen.id if item.chosen is not None else None,
                available=[
                    AssemblyVersionPublic(
                        id=row.id,
                        code=row.code,
                        version=_version(row.version_major, row.version_minor),
                    )
                    for row in item.available
                ],
                working_differs=item.working_differs,
            )
            for item in plan.items
        ],
        problems=[
            AssemblyProblemPublic(
                code=row.code, severity=row.severity, message=row.message, chapter_id=row.chapter_id
            )
            for row in plan.problems
        ],
        toc=[TocEntryPublic(**row) for row in plan.toc],
    )


def _file(result: Export) -> Response:
    # filename* с процентным кодированием: правило общее для всех выгрузок.
    name = quote(result.filename)

    return Response(
        content=result.rendered.content,
        media_type=result.rendered.media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )


@router.get("/chapters/{chapter_id}/release-gate", response_model=ReleaseGatePublic)
async def chapter_release_gate(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ReleaseGatePublic:
    """Что мешает создать финальную версию главы: коды для машины, фразы для человека."""
    gate = await ChapterReleaseService(session, context, storage).gate(chapter_id)

    return ReleaseGatePublic(
        ready=gate.ready,
        blockers=[
            BlockerPublic(code=item.code, message=item.message, count=item.count)
            for item in gate.blockers
        ],
    )


@router.get("/chapters/{chapter_id}/releases", response_model=list[ChapterReleasePublic])
async def chapter_releases(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> list[ChapterReleasePublic]:
    views = await ChapterReleaseService(session, context, storage).of_chapter(chapter_id)

    return [_chapter_release(view) for view in views]


@router.post(
    "/chapters/{chapter_id}/releases",
    response_model=ChapterReleasePublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_chapter_release(
    chapter_id: uuid.UUID,
    payload: ChapterReleaseCreate,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> ChapterReleasePublic:
    view = await ChapterReleaseService(session, context, storage).create(
        chapter_id, major=payload.major
    )

    return _chapter_release(view)


@router.get("/chapter-releases/{release_id}", response_model=ChapterReleasePublic)
async def read_chapter_release(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ChapterReleasePublic:
    return _chapter_release(await ChapterReleaseService(session, context, storage).get(release_id))


@router.get("/chapter-releases/{release_id}/manifest", response_model=ManifestPublic)
async def chapter_release_manifest(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ManifestPublic:
    """Манифест: по нему восстанавливается каждая редакция каждого блока."""
    view = await ChapterReleaseService(session, context, storage).get(release_id)
    release = view.release

    return ManifestPublic(
        manifest=release.manifest,
        manifest_hash=release.manifest_hash,
        intact=hash_manifest(release.manifest) == release.manifest_hash,
    )


@router.post("/chapter-releases/{release_id}/approve", response_model=ChapterReleasePublic)
async def approve_chapter_release(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ChapterReleasePublic:
    return _chapter_release(
        await ChapterReleaseService(session, context, storage).approve(release_id)
    )


@router.delete("/chapter-releases/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_chapter_release(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> None:
    """Отменить неутверждённую версию. Утверждённая не отменяется."""
    await ChapterReleaseService(session, context, storage).discard(release_id)


@router.get("/chapter-releases/{release_id}/changes", response_model=list[WorkingChangePublic])
async def chapter_release_changes(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> list[WorkingChangePublic]:
    """Чем рабочий текст отличается от этой версии."""
    rows = await ChapterReleaseService(session, context, storage).changes(release_id)

    return [
        WorkingChangePublic(
            block_id=row.block_id,
            code=row.code,
            final_text=row.final_text,
            working_text=row.working_text,
            changes=[ChangePublic(op=item.op, text=item.text) for item in row.changes],
        )
        for row in rows
    ]


@router.get("/chapter-releases/{release_id}/export")
async def export_chapter_release(
    release_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.DOCX,
) -> Response:
    """Читательская версия главы."""
    return _file(
        await PublicationService(session, context, storage).chapter_release(
            release_id, export_format=export_format
        )
    )


@router.get("/books/{book_id}/assembly", response_model=AssemblyPublic)
async def book_assembly(
    book_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    chosen: Annotated[list[uuid.UUID] | None, Query(alias="chapter_release_id")] = None,
) -> AssemblyPublic:
    """Что соберётся и что мешает. Без выбора подставляется последняя утверждённая версия глав."""
    return _plan(await AssemblyService(session, context).plan(book_id, chosen))


@router.post(
    "/books/{book_id}/releases",
    response_model=BookReleasePublic,
    status_code=status.HTTP_201_CREATED,
)
async def build_book_release(
    book_id: uuid.UUID,
    payload: BookReleaseCreate,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> BookReleasePublic:
    release, created = await AssemblyService(session, context).build(
        book_id, payload.chapter_release_ids, major=payload.major
    )
    if not created:
        response.status_code = status.HTTP_200_OK

    return _book_release(release, created=created)


@router.get("/books/{book_id}/releases", response_model=list[BookReleasePublic])
async def book_releases(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> list[BookReleasePublic]:
    rows = await AssemblyService(session, context).of_book(book_id)

    return [_book_release(row) for row in rows]


@router.get("/book-releases/{release_id}", response_model=BookReleasePublic)
async def read_book_release(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BookReleasePublic:
    return _book_release(await AssemblyService(session, context).get(release_id))


@router.get("/book-releases/{release_id}/export")
async def export_book_release(
    release_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.SOURCE,
) -> Response:
    """Читательская версия книги."""
    return _file(
        await PublicationService(session, context, storage).book_release(
            release_id, export_format=export_format
        )
    )


def _artifact(row: ExportArtifact) -> ArtifactPublic:
    return ArtifactPublic(
        id=row.id,
        format=row.format,
        checksum=row.checksum,
        size=row.size,
        renderer_version=row.renderer_version,
        manifest_hash=row.manifest_hash,
        page_count=row.page_count,
        superseded_at=row.superseded_at,
        created_at=row.created_at,
    )


def _gate(result: GateResult) -> GatePublic:
    release = result.release

    return GatePublic(
        release_id=release.id,
        code=release.code,
        status=release.status,
        ready=result.ready,
        checks=[
            GateCheckPublic(
                code=code,
                title=title,
                passed=not any(row.check == code for row in result.blockers),
            )
            for code, title in CHECKS
        ],
        blockers=[
            GateBlockerPublic(
                check=row.check,
                code=row.code,
                message=row.message,
                count=row.count,
                chapter_id=row.chapter_id,
                issue_id=row.issue_id,
                page_no=row.page_no,
            )
            for row in result.blockers
        ],
        passed_at=result.passed.created_at if result.passed is not None else None,
        snapshot=result.passed.gate_snapshot if result.passed is not None else None,
    )


@router.post(
    "/book-releases/{release_id}/artifacts",
    response_model=ReleaseFilesPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def render_release(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ReleaseFilesPublic:
    """Поставить сборку DOCX и PDF в очередь."""
    service = ArtifactService(session, context, storage)
    await service.request_render(release_id)

    return _files(await service.files(release_id))


@router.get("/book-releases/{release_id}/artifacts", response_model=ReleaseFilesPublic)
async def release_files(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ReleaseFilesPublic:
    return _files(await ArtifactService(session, context, storage).files(release_id))


def _files(found: ReleaseFiles) -> ReleaseFilesPublic:
    job = found.job

    return ReleaseFilesPublic(
        artifacts=[_artifact(row) for row in found.artifacts],
        previous=[_artifact(row) for row in found.previous],
        job_state=job.state if job is not None else None,
        job_error=job.error if job is not None else None,
    )


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> Response:
    service = ArtifactService(session, context, storage)
    artifact = await service.artifact(artifact_id)
    release = await service.release_of(artifact)

    return Response(
        content=await service.read(artifact),
        media_type=MEDIA_TYPES[artifact.format],
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(service.filename(release, artifact))}"
            ),
            "X-Checksum-Sha256": artifact.checksum,
        },
    )


@router.get("/artifacts/{artifact_id}/pages", response_model=list[PageAuditPublic])
async def artifact_pages(
    artifact_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> list[PageAuditPublic]:
    rows = await ArtifactService(session, context, storage).pages(artifact_id)

    return [PageAuditPublic.model_validate(row, from_attributes=True) for row in rows]


@router.get("/artifacts/{artifact_id}/pages/{page_no}/image")
async def artifact_page_image(
    artifact_id: uuid.UUID,
    page_no: Annotated[int, Path(ge=1, le=100_000)],
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> Response:
    """Страница картинкой: файл выпуска неизменяем, поэтому её можно кешировать."""
    png = await ArtifactService(session, context, storage).page_image(artifact_id, page_no)

    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/artifacts/{artifact_id}/pages/{page_no}", response_model=PageAuditPublic)
async def pass_page(
    artifact_id: uuid.UUID,
    page_no: Annotated[int, Path(ge=1, le=100_000)],
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> PageAuditPublic:
    """Страница верна."""
    row = await ArtifactService(session, context, storage).mark_page(artifact_id, page_no)

    return PageAuditPublic.model_validate(row, from_attributes=True)


@router.post("/artifacts/{artifact_id}/pages/{page_no}/issue", response_model=PageIssueResult)
async def page_issue(
    artifact_id: uuid.UUID,
    page_no: Annotated[int, Path(ge=1, le=100_000)],
    payload: PageIssueCreate,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> PageIssueResult:
    """Ошибка вёрстки: замечание со снимком страницы."""
    audit, issue = await ArtifactService(session, context, storage).register_page_issue(
        artifact_id, page_no, severity=payload.severity, description=payload.description
    )

    return PageIssueResult(
        page=PageAuditPublic.model_validate(audit, from_attributes=True),
        issue_id=issue.id,
        issue_code=issue.code,
    )


@router.get("/releases/{release_id}/gate", response_model=GatePublic)
async def release_gate(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> GatePublic:
    """Что мешает выпуску: машиночитаемые причины."""
    return _gate(await ReleaseGateService(session, context, storage).check(release_id))


@router.post("/releases/{release_id}/pass", response_model=GatePublic)
async def pass_release(
    release_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> GatePublic:
    """Выставить PASS. Те же проверки, что на экране: обойти их запросом нельзя."""
    return _gate(await ReleaseGateService(session, context, storage).pass_release(release_id))
