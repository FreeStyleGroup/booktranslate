"""Реестр ошибок.

`PATCH` и `DELETE` здесь нет намеренно. Статус меняется только действиями, у каждого своё условие;
запись не удаляется вовсе, для ненужного есть архив.
"""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.models.issue import Issue, IssueCategory, IssueSeverity, IssueStatus
from app.schemas.issue import (
    IssueAssign,
    IssueAttachmentPublic,
    IssueBrief,
    IssueCandidatePublic,
    IssueCreate,
    IssueDetailPublic,
    IssueEventPublic,
    IssueFix,
    IssueNeighbourPublic,
    IssueObjectPublic,
    IssuePagePublic,
    IssuePublic,
    IssueReclassify,
    IssueStatsPublic,
    IssueTermPublic,
    OptionalNote,
    RequiredNote,
)
from app.schemas.paging import SortOrder
from app.services.exporting import EXPORT_ROLES
from app.services.issue_attachments import IssueAttachments
from app.services.issue_export import (
    EXPORT_CEILING,
    MEDIA_TYPES,
    IssueExportFormat,
    to_csv,
    to_xlsx,
)
from app.services.issues import IssueFilter, IssueRow, IssueService, IssueSort, IssueView

router = APIRouter(tags=["issues"])

# Тот же запрет, что у изображений объектов: файл показывается, но ничего не выполняет.
_FILE_POLICY = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
_SHOWN_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


def _public(row: IssueRow) -> IssuePublic:
    issue = row.issue

    return IssuePublic(
        id=issue.id,
        code=issue.code,
        book_id=issue.book_id,
        book_title=row.book_title,
        chapter_id=issue.chapter_id,
        block_id=issue.block_id,
        block_code=row.block_code,
        object_id=issue.object_id,
        object_code=row.object_code,
        parent_issue_id=issue.parent_issue_id,
        category=issue.category,
        severity=issue.severity,
        status=issue.status,
        priority_score=issue.priority_score,
        impact_count=issue.impact_count,
        automatic=issue.automatic,
        detected_by=row.detected_by,
        assignee_id=issue.assignee_id,
        assignee=row.assignee,
        description=issue.description,
        archived_at=issue.archived_at,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
    )


def _brief(issue: Issue) -> IssueBrief:
    return IssueBrief(id=issue.id, code=issue.code, status=issue.status)


def _detail(view: IssueView) -> IssueDetailPublic:
    issue = view.row.issue
    prefix = f"{view.chapter.code}-" if view.chapter.code is not None else ""

    return IssueDetailPublic(
        **_public(view.row).model_dump(),
        chapter_label=view.chapter.title,
        source_snapshot=issue.source_snapshot,
        target_snapshot=issue.target_snapshot,
        proposed_fix=issue.proposed_fix,
        discovered_revision_id=issue.discovered_revision_id,
        fix_revision_id=issue.fix_revision_id,
        current_revision_id=view.current.id if view.current is not None else None,
        current_text=view.current.text if view.current is not None else None,
        subject_active=view.block_active,
        context=[
            IssueNeighbourPublic(
                block_id=item.block.id,
                code=prefix + item.block.code,
                source_text=item.block.source_text,
                translation=item.translation,
            )
            for item in view.context
        ],
        terms=[
            IssueTermPublic(
                source=term.source, target=term.target, mandatory=term.mandatory, note=term.note
            )
            for term in view.terms
        ],
        objects=[
            IssueObjectPublic(
                id=item.object.id, code=prefix + item.object.code, type=item.object.type
            )
            for item in view.objects
        ],
        events=[
            IssueEventPublic(
                id=row.event.id,
                kind=row.event.kind,
                from_status=row.event.from_status,
                to_status=row.event.to_status,
                actor=row.actor,
                note=row.event.note,
                related_revision_id=row.event.related_revision_id,
                payload=row.event.payload,
                created_at=row.event.created_at,
            )
            for row in view.events
        ],
        attachments=[
            IssueAttachmentPublic.model_validate(item, from_attributes=True)
            for item in view.attachments
        ],
        candidates=[
            IssueCandidatePublic(
                revision_id=item.revision.id,
                revision_no=item.revision.revision_no,
                block_code=prefix + item.block.code,
                text=item.revision.text,
            )
            for item in view.candidates
        ],
        children=[_brief(child) for child in view.children],
        parent=_brief(view.parent) if view.parent is not None else None,
        actions=view.actions,
        review_note=view.review_note,
    )


def _filter(
    book_id: uuid.UUID | None,
    chapter_id: uuid.UUID | None,
    block_id: uuid.UUID | None,
    object_id: uuid.UUID | None,
    state: list[IssueStatus] | None,
    severity: IssueSeverity | None,
    category: IssueCategory | None,
    assignee_id: uuid.UUID | None,
    query: str | None,
    archived: bool,
) -> IssueFilter:
    return IssueFilter(
        book_id=book_id,
        chapter_id=chapter_id,
        block_id=block_id,
        object_id=object_id,
        statuses=tuple(state or ()),
        severity=severity,
        category=category,
        assignee_id=assignee_id,
        query=query,
        archived=archived,
    )


async def _answer(service: IssueService, issue: Issue) -> IssuePublic:
    [row] = await service.rows_of([issue])

    return _public(row)


QueryText = Annotated[str | None, Query(max_length=200)]


@router.post("/issues", response_model=IssueDetailPublic, status_code=status.HTTP_201_CREATED)
async def register_issue(
    payload: IssueCreate, context: ContextDep, session: SessionDep, storage: StorageDep
) -> IssueDetailPublic:
    """Зарегистрировать ошибку. Код и снимки подставляет сервер."""
    service = IssueService(session, context, storage)
    issue = await service.register(
        block_id=payload.block_id,
        object_id=payload.object_id,
        category=payload.category,
        severity=payload.severity,
        description=payload.description,
        proposed_fix=payload.proposed_fix,
        parent_issue_id=payload.parent_issue_id,
        assignee_id=payload.assignee_id,
    )

    return _detail(await service.view(issue.id))


@router.get("/issues", response_model=IssuePagePublic)
async def list_issues(
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    book_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    block_id: uuid.UUID | None = None,
    object_id: uuid.UUID | None = None,
    state: Annotated[list[IssueStatus] | None, Query()] = None,
    severity: IssueSeverity | None = None,
    category: IssueCategory | None = None,
    assignee_id: uuid.UUID | None = None,
    query: QueryText = None,
    archived: bool = False,
    sort: IssueSort = IssueSort.PRIORITY,
    order: SortOrder = SortOrder.DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IssuePagePublic:
    page = await IssueService(session, context, storage).page(
        _filter(
            book_id,
            chapter_id,
            block_id,
            object_id,
            state,
            severity,
            category,
            assignee_id,
            query,
            archived,
        ),
        sort=sort,
        descending=order is SortOrder.DESC,
        limit=limit,
        offset=offset,
    )

    return IssuePagePublic(total=page.total, items=[_public(row) for row in page.items])


@router.get("/issues/stats", response_model=IssueStatsPublic)
async def issue_stats(
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    book_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
) -> IssueStatsPublic:
    """Счёт по разрядам. Незакрытые критичные и серьёзные считаются здесь и нигде больше."""
    stats = await IssueService(session, context, storage).stats(
        IssueFilter(book_id=book_id, chapter_id=chapter_id)
    )

    return IssueStatsPublic(
        total=stats.total,
        by_status=stats.by_status,
        by_severity=stats.by_severity,
        by_category=stats.by_category,
        open_critical=stats.open_critical,
        open_major=stats.open_major,
    )


@router.get("/issues/export")
async def export_issues(
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    export_format: Annotated[IssueExportFormat, Query(alias="format")] = IssueExportFormat.CSV,
    book_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    state: Annotated[list[IssueStatus] | None, Query()] = None,
    severity: IssueSeverity | None = None,
    category: IssueCategory | None = None,
    assignee_id: uuid.UUID | None = None,
    query: QueryText = None,
    archived: bool = False,
) -> Response:
    """Выгрузка отбора целиком: те же условия, что у списка, без страниц."""
    context.require(*EXPORT_ROLES)

    rows = await IssueService(session, context, storage).everything(
        _filter(
            book_id, chapter_id, None, None, state, severity, category, assignee_id, query, archived
        ),
        ceiling=EXPORT_CEILING,
    )
    body = to_xlsx(rows) if export_format is IssueExportFormat.XLSX else to_csv(rows)
    name = quote(f"реестр-ошибок.{export_format.value}")

    return Response(
        content=body,
        media_type=MEDIA_TYPES[export_format],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{name}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/issues/{issue_id}", response_model=IssueDetailPublic)
async def read_issue(
    issue_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> IssueDetailPublic:
    """Всё для проверки: снимки, текущий текст, соседи, термины, объекты, лента."""
    return _detail(await IssueService(session, context, storage).view(issue_id))


@router.post("/issues/{issue_id}/confirm", response_model=IssuePublic)
async def confirm_issue(
    issue_id: uuid.UUID,
    payload: OptionalNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.confirm(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/reject", response_model=IssuePublic)
async def reject_issue(
    issue_id: uuid.UUID,
    payload: RequiredNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.reject(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/clarification", response_model=IssuePublic)
async def request_clarification(
    issue_id: uuid.UUID,
    payload: RequiredNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.request_clarification(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/clarification/answer", response_model=IssuePublic)
async def answer_clarification(
    issue_id: uuid.UUID,
    payload: RequiredNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.answer_clarification(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/fix", response_model=IssuePublic)
async def fix_issue(
    issue_id: uuid.UUID,
    payload: IssueFix,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    """Связать замечание с исправляющей редакцией. Без неё статус не меняется."""
    service = IssueService(session, context, storage)

    return await _answer(
        service, await service.fix(issue_id, revision_id=payload.revision_id, note=payload.note)
    )


@router.post("/issues/{issue_id}/verification", response_model=IssuePublic)
async def verify_issue(
    issue_id: uuid.UUID,
    payload: OptionalNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.verify(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/close", response_model=IssuePublic)
async def close_issue(
    issue_id: uuid.UUID,
    payload: OptionalNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.close(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/reopen", response_model=IssuePublic)
async def reopen_issue(
    issue_id: uuid.UUID,
    payload: RequiredNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.reopen(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/classification", response_model=IssuePublic)
async def reclassify_issue(
    issue_id: uuid.UUID,
    payload: IssueReclassify,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(
        service,
        await service.reclassify(
            issue_id, reason=payload.reason, category=payload.category, severity=payload.severity
        ),
    )


@router.post("/issues/{issue_id}/assignee", response_model=IssuePublic)
async def assign_issue(
    issue_id: uuid.UUID,
    payload: IssueAssign,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.assign(issue_id, assignee_id=payload.assignee_id))


@router.post("/issues/{issue_id}/comments", response_model=IssuePublic)
async def comment_issue(
    issue_id: uuid.UUID,
    payload: RequiredNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.comment(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/archive", response_model=IssuePublic)
async def archive_issue(
    issue_id: uuid.UUID,
    payload: OptionalNote,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.archive(issue_id, note=payload.note))


@router.post("/issues/{issue_id}/restore", response_model=IssuePublic)
async def restore_issue(
    issue_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> IssuePublic:
    service = IssueService(session, context, storage)

    return await _answer(service, await service.restore(issue_id))


@router.post(
    "/issues/{issue_id}/attachments",
    response_model=IssueAttachmentPublic,
    status_code=status.HTTP_201_CREATED,
)
async def attach_to_issue(
    issue_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File(description="Снимок страницы или формулы")],
) -> IssueAttachmentPublic:
    attachment = await IssueAttachments(session, context, storage).accept(
        issue_id, file=file, filename=file.filename
    )

    return IssueAttachmentPublic.model_validate(attachment, from_attributes=True)


@router.get("/issues/{issue_id}/attachments/{attachment_id}")
async def read_attachment(
    issue_id: uuid.UUID,
    attachment_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> StreamingResponse:
    service = IssueAttachments(session, context, storage)
    attachment = await service.get(issue_id, attachment_id)
    shown = attachment.media_type in _SHOWN_TYPES
    name = quote(attachment.filename)

    return StreamingResponse(
        service.stream(attachment),
        media_type=attachment.media_type if shown else "application/octet-stream",
        headers={
            "Content-Disposition": ("inline" if shown else f"attachment; filename*=UTF-8''{name}"),
            # Тип определён по байтам при приёме, и угадывать его браузеру незачем.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": _FILE_POLICY,
            "Content-Length": str(attachment.size_bytes),
        },
    )
