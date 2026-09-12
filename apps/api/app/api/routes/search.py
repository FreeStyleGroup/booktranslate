"""Общий поиск по рабочему пространству."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContextDep, SessionDep
from app.schemas.catalog import CatalogEntryPublic
from app.schemas.document import DocumentPublic
from app.schemas.finder import (
    DocumentHits,
    EntryHits,
    SearchResult,
    SegmentHitPublic,
    SegmentHits,
    TermHits,
)
from app.schemas.glossary import GlossaryTermPublic
from app.services.finder import MIN_QUERY, Finder

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResult)
async def search(
    context: ContextDep,
    session: SessionDep,
    query: Annotated[
        str,
        Query(min_length=MIN_QUERY, max_length=200, description="Подстрока без учёта регистра"),
    ],
    limit: Annotated[int, Query(ge=1, le=50, description="Сколько показать из каждой группы")] = 5,
) -> SearchResult:
    """Найти слово везде, где оно может лежать: книги, словарь, справки, текст.

    Из каждой группы отдаётся немного, а общее число считается по всей
    базе: по нему видно, что находок больше, и куда за ними идти.
    """
    found = await Finder(session, context).find(query, per_group=limit)

    return SearchResult(
        query=query,
        documents=DocumentHits(
            total=found.documents.total,
            items=[DocumentPublic.model_validate(item) for item in found.documents.items],
        ),
        terms=TermHits(
            total=found.terms.total,
            items=[GlossaryTermPublic.model_validate(item) for item in found.terms.items],
        ),
        entries=EntryHits(
            total=found.entries.total,
            items=[CatalogEntryPublic.model_validate(item) for item in found.entries.items],
        ),
        segments=SegmentHits(
            total=found.segments.total,
            items=[SegmentHitPublic.model_validate(item) for item in found.segments.items],
        ),
    )
