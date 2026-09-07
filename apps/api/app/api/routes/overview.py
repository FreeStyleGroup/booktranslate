"""Сводка по рабочему пространству."""

from fastapi import APIRouter

from app.api.deps import ContextDep, SessionDep
from app.schemas.overview import (
    DocumentProgress,
    FindingPreview,
    OverviewPublic,
    UsageSummary,
)
from app.services.overview import OverviewService
from app.services.pricing import estimate_usd

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewPublic)
async def overview(context: ContextDep, session: SessionDep) -> OverviewPublic:
    """Что в работе, где ждут человека и во сколько это обошлось.

    Один запрос вместо десятка со стороны витрины: кабинет открывают чаще
    всего, и собирать его по частям значит открывать три секунды.
    """
    summary = await OverviewService(session, context).build()

    return OverviewPublic(
        projects=summary.projects,
        documents=summary.documents,
        segments=summary.segments,
        documents_by_status=summary.documents_by_status,
        segments_by_status=summary.segments_by_status,
        flagged=summary.flagged,
        undecided_terms=summary.undecided_terms,
        glossary_terms=summary.glossary_terms,
        catalog_entries=summary.catalog_entries,
        memory_units=summary.memory_units,
        usage=UsageSummary(
            input_tokens=summary.usage.input_tokens,
            output_tokens=summary.usage.output_tokens,
            cached_input_tokens=summary.usage.cached_input_tokens,
            cache_write_tokens=summary.usage.cache_write_tokens,
            translated_by=summary.translated_by,
            estimated_usd=estimate_usd(
                summary.translated_by or "",
                input_tokens=summary.usage.input_tokens,
                output_tokens=summary.usage.output_tokens,
                cached_input_tokens=summary.usage.cached_input_tokens,
                cache_write_tokens=summary.usage.cache_write_tokens,
            ),
        ),
        recent_documents=[
            DocumentProgress(
                id=card.id,
                title=card.title,
                status=card.status,
                segments=card.segments,
                done=card.done,
                ready_percent=card.ready_percent,
            )
            for card in summary.recent_documents
        ],
        recent_findings=[
            FindingPreview(
                segment_id=card.segment_id,
                document_id=card.document_id,
                document_title=card.document_title,
                position=card.position,
                source_text=card.source_text,
                target_text=card.target_text,
                checks=card.checks,
            )
            for card in summary.recent_findings
        ],
    )
