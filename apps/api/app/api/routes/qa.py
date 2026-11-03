"""Проверки главы: запуск, состояние, очередь находок.

Остановка — общая для всей очереди: `POST /jobs/{id}/cancel`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep
from app.models.issue import IssueCategory, IssueSeverity
from app.models.qa import FindingDisposition, QAKind
from app.schemas.qa import (
    ChapterChecksPublic,
    QAFindingPage,
    QAFindingPublic,
    QARunPublic,
    QAStart,
)
from app.services.qa import FindingRow, QAService, RunView

router = APIRouter(tags=["qa"])


def _run(view: RunView) -> QARunPublic:
    run, job = view.run, view.job

    return QARunPublic(
        id=run.id,
        chapter_id=run.chapter_id,
        kind=run.kind,
        scope=run.scope,
        check_profile_version=run.check_profile_version,
        revision_set_hash=run.revision_set_hash,
        model=run.model,
        blocks_total=run.blocks_total,
        blocks_checked=run.blocks_checked,
        blocks_untranslated=run.blocks_untranslated,
        findings_total=run.findings_total,
        issues_created=run.issues_created,
        rejections=run.rejections,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        job_id=job.id if job is not None else None,
        state=job.state if job is not None else None,
        error=job.error if job is not None else None,
        created_at=run.created_at,
    )


def _finding(row: FindingRow) -> QAFindingPublic:
    finding = row.finding

    return QAFindingPublic(
        id=finding.id,
        qa_run_id=finding.qa_run_id,
        book_id=row.book_id,
        chapter_id=row.chapter_id,
        block_id=finding.block_id,
        block_code=row.block_code,
        revision_id=finding.revision_id,
        kind=finding.kind,
        check=finding.check_name,
        message=finding.message,
        category=finding.category,
        severity=finding.severity,
        disposition=finding.disposition,
        rule=finding.rule,
        issue_id=finding.issue_id,
        issue_code=row.issue_code,
        issue_status=row.issue_status,
        created_at=finding.created_at,
    )


@router.post(
    "/chapters/{chapter_id}/qa", response_model=QARunPublic, status_code=status.HTTP_201_CREATED
)
async def start_qa(
    chapter_id: uuid.UUID, payload: QAStart, context: ContextDep, session: SessionDep
) -> QARunPublic:
    """Поставить проверку в очередь. Живое задание на главу одно: идёт перевод — будет 409."""
    return _run(await QAService(session, context).start(chapter_id, payload.kind))


@router.get("/chapters/{chapter_id}/qa", response_model=ChapterChecksPublic)
async def chapter_checks(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> ChapterChecksPublic:
    state = await QAService(session, context).state(chapter_id)

    return ChapterChecksPublic(
        total=state.total,
        translated=state.translated,
        formal=state.formal,
        semantic=state.semantic,
        revision_set_hash=state.revision_set_hash,
        latest_formal=_run(state.latest_formal) if state.latest_formal is not None else None,
        latest_semantic=_run(state.latest_semantic) if state.latest_semantic is not None else None,
        live=_run(state.live) if state.live is not None else None,
        semantic_scope=state.semantic_scope,
    )


@router.get("/qa/findings", response_model=QAFindingPage)
async def qa_findings(
    context: ContextDep,
    session: SessionDep,
    book_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    kind: QAKind | None = None,
    check: Annotated[str | None, Query(max_length=40)] = None,
    severity: IssueSeverity | None = None,
    category: IssueCategory | None = None,
    disposition: FindingDisposition | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QAFindingPage:
    """Очередь проверок: каждая находка связана с замечанием или с правилом, почему его нет."""
    page = await QAService(session, context).findings(
        book_id=book_id,
        chapter_id=chapter_id,
        run_id=run_id,
        kind=kind,
        check=check,
        severity=severity,
        category=category,
        disposition=disposition,
        limit=limit,
        offset=offset,
    )

    return QAFindingPage(total=page.total, items=[_finding(row) for row in page.items])


@router.get("/qa/runs", response_model=list[QARunPublic])
async def qa_runs(
    context: ContextDep,
    session: SessionDep,
    chapter_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[QARunPublic]:
    return [
        _run(view)
        for view in await QAService(session, context).runs(chapter_id=chapter_id, limit=limit)
    ]
