"""Сводка по рабочему пространству."""

from fastapi import APIRouter

from app.api.deps import ContextDep, SessionDep
from app.schemas.overview import (
    AttentionPreview,
    BookProgress,
    OverviewPublic,
    UsageSummary,
)
from app.services.overview import OverviewService

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewPublic)
async def overview(context: ContextDep, session: SessionDep) -> OverviewPublic:
    """Что в работе, где ждут человека и во сколько это обошлось.

    Один запрос вместо десятка со стороны витрины: сводку открывают чаще всего, и
    собирать её по частям значит открывать кабинет секундами.
    """
    summary = await OverviewService(session, context).build()

    return OverviewPublic(
        projects=summary.projects,
        books=summary.books,
        documents=summary.documents,
        blocks=summary.blocks,
        translated=summary.translated,
        by_origin=summary.by_origin,
        live_runs=summary.live_runs,
        undecided_terms=summary.undecided_terms,
        glossary_terms=summary.glossary_terms,
        catalog_entries=summary.catalog_entries,
        memory_units=summary.memory_units,
        usage=UsageSummary(
            input_tokens=summary.usage.input_tokens,
            output_tokens=summary.usage.output_tokens,
            cached_input_tokens=summary.usage.cached_input_tokens,
            cache_write_tokens=summary.usage.cache_write_tokens,
            estimated_usd=summary.estimated_usd,
        ),
        recent_books=[
            BookProgress(
                id=card.id,
                code=card.code,
                title=card.title,
                blocks=card.blocks,
                translated=card.translated,
                ready_percent=card.ready_percent,
            )
            for card in summary.recent_books
        ],
        attention=[
            AttentionPreview(
                run_id=card.run_id,
                book_id=card.book_id,
                chapter_id=card.chapter_id,
                title=card.title,
                problem=card.problem,
            )
            for card in summary.attention
        ],
    )
