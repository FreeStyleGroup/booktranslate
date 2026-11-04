"""Автоматический режим: одна кнопка на книгу и честное состояние: где она и что её держит."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.schemas.autopilot import (
    AutopilotPublic,
    AutopilotReasonPublic,
    AutopilotResume,
    AutopilotStagePublic,
    AutopilotStart,
    AutopilotState,
)
from app.services.autopilot import STAGES, AutopilotService, AutopilotView

router = APIRouter(tags=["autopilot"])


def _public(view: AutopilotView) -> AutopilotPublic:
    run = view.run
    codes = [code for code, _ in STAGES]
    position = codes.index(run.stage) if run.stage in codes else 0

    return AutopilotPublic(
        id=run.id,
        book_id=run.book_id,
        status=run.status,
        stage=run.stage,
        stages=[
            AutopilotStagePublic(
                code=code,
                title=title,
                state=(
                    "done"
                    if index < position or run.stage == "done"
                    else "current"
                    if index == position
                    else "pending"
                ),
            )
            for index, (code, title) in enumerate(STAGES)
        ],
        waiting=[AutopilotReasonPublic(**row) for row in run.waiting],
        profile=run.profile,
        chapters_total=view.chapters_total,
        chapters_done=view.chapters_done,
        release_id=run.release_id,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


@router.get("/books/{book_id}/autopilot", response_model=AutopilotState)
async def autopilot_state(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> AutopilotState:
    view = await AutopilotService(session, context, storage).latest(book_id)

    return AutopilotState(run=_public(view) if view is not None else None)


@router.post(
    "/books/{book_id}/autopilot", response_model=AutopilotState, status_code=status.HTTP_201_CREATED
)
async def start_autopilot(
    book_id: uuid.UUID,
    payload: AutopilotStart,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> AutopilotState:
    """Перевести книгу без участия человека. Если решить уверенно нельзя, прогон остановится."""
    service = AutopilotService(session, context, storage)
    await service.start(
        book_id,
        term_min_frequency=payload.term_min_frequency,
        semantic=payload.semantic,
        budget_usd=payload.budget_usd,
    )
    view = await service.latest(book_id)

    return AutopilotState(run=_public(view) if view is not None else None)


@router.post("/autopilot-runs/{run_id}/resume", response_model=AutopilotState)
async def resume_autopilot(
    run_id: uuid.UUID,
    payload: AutopilotResume,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> AutopilotState:
    """Человек решил то, что держало прогон: продолжить."""
    service = AutopilotService(session, context, storage)
    run = await service.resume(run_id, budget_usd=payload.budget_usd)
    view = await service.latest(run.book_id)

    return AutopilotState(run=_public(view) if view is not None else None)


@router.post("/autopilot-runs/{run_id}/cancel", response_model=AutopilotState)
async def cancel_autopilot(
    run_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> AutopilotState:
    service = AutopilotService(session, context, storage)
    run = await service.cancel(run_id)
    view = await service.latest(run.book_id)

    return AutopilotState(run=_public(view) if view is not None else None)
