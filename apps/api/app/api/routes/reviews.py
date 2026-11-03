"""Редактура и финальная сверка главы.

Отметки ставятся по одному месту. Массовой отметки нет намеренно: «сверено», поставленное не глядя,
ничего не стоит, а выпуск опирается именно на него.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.schemas.review import (
    ChapterReviewsPublic,
    EditPreview,
    EditPreviewResult,
    LinkedObjectPublic,
    LiteraryEdit,
    LiteraryEditResult,
    MarkBlock,
    MarkObject,
    NeighbourPublic,
    NextBlockPublic,
    NextItemPublic,
    NextObjectPublic,
    OpenIssuePublic,
    ReviewRunPublic,
    ReviewStart,
    ReviewTermPublic,
)
from app.services.reviews import NextItem, ReviewService, RunView

router = APIRouter(tags=["reviews"])


def _run(view: RunView) -> ReviewRunPublic:
    run, progress = view.run, view.progress

    return ReviewRunPublic(
        id=run.id,
        book_id=run.book_id,
        book_title=view.book_title,
        chapter_id=run.chapter_id,
        chapter_title=view.chapter_title,
        kind=run.kind,
        status=run.status,
        reviewer=view.reviewer,
        base_revision_set_hash=run.base_revision_set_hash,
        completed_revision_set_hash=run.completed_revision_set_hash,
        completed_at=run.completed_at,
        created_at=run.created_at,
        stale=view.stale,
        blocks_total=progress.blocks_total,
        blocks_done=progress.blocks_done,
        objects_total=progress.objects_total,
        objects_done=progress.objects_done,
        untranslated=progress.untranslated,
        complete=progress.complete,
    )


def _issues(item: NextItem) -> list[OpenIssuePublic]:
    return [
        OpenIssuePublic(id=row.id, code=row.code, severity=row.severity, status=row.status)
        for row in item.issues
    ]


def _next(item: NextItem | None) -> NextItemPublic:
    if item is None:
        return NextItemPublic(block=None, object=None)

    prefix = item.prefix

    if item.block is not None and item.current is not None:
        return NextItemPublic(
            block=NextBlockPublic(
                id=item.block.id,
                code=prefix + item.block.code,
                ordinal=item.block.ordinal,
                kind=item.block.kind,
                source_text=item.block.source_text,
                revision_id=item.current.id,
                revision_no=item.current.revision_no,
                text=item.current.text,
                protected=item.protected,
                context=[
                    NeighbourPublic(
                        code=prefix + row.block.code,
                        ordinal=row.block.ordinal,
                        source_text=row.block.source_text,
                        translation=row.translation,
                    )
                    for row in item.context
                ],
                terms=[
                    ReviewTermPublic(
                        source=term.source, target=term.target, mandatory=term.mandatory
                    )
                    for term in item.terms
                ],
                objects=[
                    LinkedObjectPublic(
                        id=row.object.id,
                        chapter_id=row.object.chapter_id,
                        code=row.code,
                        type=row.object.type,
                        relation=row.relation,
                    )
                    for row in item.linked
                ],
                issues=_issues(item),
            ),
            object=None,
        )

    assert item.object is not None
    assert item.object_hash is not None

    return NextItemPublic(
        block=None,
        object=NextObjectPublic(
            id=item.object.id,
            code=prefix + item.object.code,
            type=item.object.type,
            content_hash=item.object_hash,
            position=item.object_position,
            source_text="\n".join(block.source_text for block in item.object_blocks),
            translation=item.object_translation,
            issues=_issues(item),
        ),
    )


@router.post(
    "/chapters/{chapter_id}/reviews",
    response_model=ReviewRunPublic,
    status_code=status.HTTP_201_CREATED,
)
async def start_review(
    chapter_id: uuid.UUID,
    payload: ReviewStart,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> ReviewRunPublic:
    return _run(await ReviewService(session, context, storage).start(chapter_id, payload.kind))


@router.get("/chapters/{chapter_id}/reviews", response_model=ChapterReviewsPublic)
async def chapter_reviews(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ChapterReviewsPublic:
    found = await ReviewService(session, context, storage).of_chapter(chapter_id)

    return ChapterReviewsPublic(
        technical=_run(found.technical) if found.technical is not None else None,
        literary=_run(found.literary) if found.literary is not None else None,
        final_compare=_run(found.final_compare) if found.final_compare is not None else None,
    )


@router.get("/review-runs/{run_id}", response_model=ReviewRunPublic)
async def read_review(
    run_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ReviewRunPublic:
    return _run(await ReviewService(session, context, storage).get(run_id))


@router.get("/review-runs/{run_id}/next", response_model=NextItemPublic)
async def next_unreviewed(
    run_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    after: Annotated[int, Query(ge=-1)] = -1,
    after_object: Annotated[int, Query(ge=-1)] = -1,
) -> NextItemPublic:
    """Следующее непросмотренное: `after` — блок, с которого продолжать, `after_object` — объект."""
    item = await ReviewService(session, context, storage).next_item(
        run_id, after=after, after_object=after_object
    )

    return _next(item)


@router.post("/review-runs/{run_id}/blocks", response_model=ReviewRunPublic)
async def mark_block(
    run_id: uuid.UUID,
    payload: MarkBlock,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> ReviewRunPublic:
    return _run(
        await ReviewService(session, context, storage).mark_block(
            run_id,
            block_id=payload.block_id,
            revision_id=payload.revision_id,
            result=payload.result,
            note=payload.note,
        )
    )


@router.post("/review-runs/{run_id}/objects", response_model=ReviewRunPublic)
async def mark_object(
    run_id: uuid.UUID,
    payload: MarkObject,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> ReviewRunPublic:
    return _run(
        await ReviewService(session, context, storage).mark_object(
            run_id,
            object_id=payload.object_id,
            digest=payload.content_hash,
            result=payload.result,
            note=payload.note,
        )
    )


@router.post("/review-runs/{run_id}/edit", response_model=LiteraryEditResult)
async def literary_edit(
    run_id: uuid.UUID,
    payload: LiteraryEdit,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> LiteraryEditResult:
    """Литературная правка. Изменение защищённого без подтверждения — 409 со списком."""
    view, violations = await ReviewService(session, context, storage).literary_edit(
        run_id,
        block_id=payload.block_id,
        base_revision_id=payload.base_revision_id,
        text=payload.text,
        reason=payload.reason,
        note=payload.note,
        accept_violation=payload.accept_violation,
        issue_id=payload.issue_id,
    )

    return LiteraryEditResult(run=_run(view), violations=violations)


@router.post("/review-runs/{run_id}/edit/preview", response_model=EditPreviewResult)
async def preview_literary_edit(
    run_id: uuid.UUID,
    payload: EditPreview,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> EditPreviewResult:
    """Что правка изменит из защищённого. Ничего не сохраняет."""
    violations = await ReviewService(session, context, storage).preview_edit(
        run_id,
        block_id=payload.block_id,
        base_revision_id=payload.base_revision_id,
        text=payload.text,
    )

    return EditPreviewResult(violations=violations)


@router.post("/review-runs/{run_id}/complete", response_model=ReviewRunPublic)
async def complete_review(
    run_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> ReviewRunPublic:
    return _run(await ReviewService(session, context, storage).complete(run_id))
