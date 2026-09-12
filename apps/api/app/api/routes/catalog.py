"""Каталог терминов: справки и поиск незнакомых слов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContextDep, LookupDep, SessionDep
from app.schemas.catalog import (
    CatalogEntryPublic,
    CatalogLookupReport,
    CatalogSourcePublic,
    DocumentLookupRequest,
    TermLookupRequest,
)
from app.services.catalog import CatalogService, LookupReport, Unknown
from app.services.pricing import estimate_usd
from app.services.providers.lookup import OFFLINE

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=list[CatalogEntryPublic])
async def list_catalog(
    context: ContextDep,
    session: SessionDep,
    lookup: LookupDep,
    query: Annotated[
        str | None, Query(description="Часть термина, перевода или определения")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CatalogEntryPublic]:
    """Что бюро уже выяснило.

    Поиск идёт и по определению: человек помнит «что-то про проскальзывание
    цены» чаще, чем точное написание термина.
    """
    entries = await CatalogService(session, context, lookup).search(
        query=query, limit=limit, offset=offset
    )

    return [CatalogEntryPublic.model_validate(entry) for entry in entries]


@router.get("/catalog/source", response_model=CatalogSourcePublic)
async def catalog_source(lookup: LookupDep) -> CatalogSourcePublic:
    """Чем отвечает справочник сейчас.

    Витрине это нужно до запроса, а не после: выключенный источник
    отвечает «не нашёл» на всё, и без предупреждения человек решил бы, что
    слова нет в сети.
    """
    return CatalogSourcePublic(name=lookup.name, online=lookup.name != OFFLINE)


@router.post("/catalog/lookup", response_model=CatalogLookupReport)
async def lookup_terms(
    payload: TermLookupRequest,
    context: ContextDep,
    session: SessionDep,
    lookup: LookupDep,
) -> CatalogLookupReport:
    """Посмотреть незнакомые слова во внешнем источнике.

    Сначала каталог, потом сеть: уже выясненное не спрашивается заново, и по
    ответу видно, сколько справок досталось бесплатно.

    Найденное — предложение, а не решение: в словарь оно попадает только
    через человека. Слово, записанное туда без проверки, разойдётся по всей
    книге и будет выглядеть согласованным.
    """
    report = await CatalogService(session, context, lookup).explain(
        [Unknown(source_term=term, sample=payload.sample or "") for term in payload.terms],
        source_language=payload.source_language,
        target_language=payload.target_language,
        subject=payload.subject,
        refresh=payload.refresh,
    )

    return _report(report, lookup.name)


@router.post("/documents/{document_id}/terminology/lookup", response_model=CatalogLookupReport)
async def lookup_candidates(
    document_id: uuid.UUID,
    payload: DocumentLookupRequest,
    context: ContextDep,
    session: SessionDep,
    lookup: LookupDep,
) -> CatalogLookupReport:
    """Разобраться с кандидатами документа.

    Без списка берутся самые частые из нерешённых: слово, встреченное сорок
    раз, стоит справки больше, чем случайное из подписи к рисунку. Отрывок
    из книги уходит в запрос вместе с термином — одно и то же слово в разных
    отраслях значит разное.
    """
    report = await CatalogService(session, context, lookup).explain_document(
        document_id,
        candidate_ids=payload.candidate_ids or None,
        limit=payload.limit,
        refresh=payload.refresh,
    )

    return _report(report, lookup.name)


def _report(report: LookupReport, source: str) -> CatalogLookupReport:
    return CatalogLookupReport(
        entries=[CatalogEntryPublic.model_validate(entry) for entry in report.entries],
        from_catalog=report.from_catalog,
        asked=report.asked,
        found=report.found,
        input_tokens=report.usage.input_tokens,
        output_tokens=report.usage.output_tokens,
        cached_input_tokens=report.usage.cached_input_tokens,
        cache_write_tokens=report.usage.cache_write_tokens,
        searches=report.searches,
        estimated_usd=estimate_usd(
            source,
            input_tokens=report.usage.input_tokens,
            output_tokens=report.usage.output_tokens,
            cached_input_tokens=report.usage.cached_input_tokens,
            cache_write_tokens=report.usage.cache_write_tokens,
            searches=report.searches,
        ),
    )
