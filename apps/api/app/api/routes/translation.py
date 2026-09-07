"""Перевод документа и словарь терминов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContextDep, ProviderDep, SessionDep
from app.schemas.glossary import (
    GlossaryTermCreate,
    GlossaryTermPublic,
    GlossaryTermUpdate,
    TranslationResult,
)
from app.services.glossary import GlossaryService
from app.services.translation import TranslationService

router = APIRouter(tags=["translation"])


@router.post("/documents/{document_id}/translate", response_model=TranslationResult)
async def translate_document(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    provider: ProviderDep,
    force: Annotated[
        bool,
        Query(description="Переводить заново, включая отредактированные и принятые сегменты"),
    ] = False,
    ignore_terminology: Annotated[
        bool,
        Query(description="Переводить, не дожидаясь решений по кандидатам в словарь"),
    ] = False,
) -> TranslationResult:
    """Перевести сегменты документа.

    По умолчанию берутся только непереведённые: повторный запуск не трогает
    правку человека. Ответ — не список сегментов, а сводка: их могут быть
    десятки тысяч, а по сводке видно, сколько закрыто памятью и сколько
    пришлось отдать модели.

    Незаконченный терминологический проход останавливает перевод: словарь,
    решённый наполовину, даёт в книге два названия для одной вещи. Обойти
    это можно (`ignore_terminology`), но это осознанный шаг, а не умолчание.
    """
    summary = await TranslationService(session, context, provider).translate(
        document_id, force=force, ignore_terminology=ignore_terminology
    )

    return TranslationResult(
        total=summary.total,
        from_memory=summary.from_memory,
        from_provider=summary.from_provider,
        flagged=summary.flagged,
        unique_texts=summary.unique_texts,
        provider_calls=summary.provider_calls,
        saved_calls=summary.saved_calls,
    )


@router.get("/glossary", response_model=list[GlossaryTermPublic])
async def list_glossary(
    context: ContextDep,
    session: SessionDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GlossaryTermPublic]:
    terms = await GlossaryService(session, context).list(
        project_id=project_id, limit=limit, offset=offset
    )

    return [GlossaryTermPublic.model_validate(term) for term in terms]


@router.post("/glossary", response_model=GlossaryTermPublic, status_code=status.HTTP_201_CREATED)
async def add_glossary_term(
    payload: GlossaryTermCreate, context: ContextDep, session: SessionDep
) -> GlossaryTermPublic:
    """Завести термин либо уточнить существующий.

    Повторное добавление того же термина — правка, а не ошибка: человек
    уточняет перевод, а не заводит вторую такую же запись.
    """
    term = await GlossaryService(session, context).add(
        source_term=payload.source_term,
        target_term=payload.target_term,
        source_language=payload.source_language,
        target_language=payload.target_language,
        project_id=payload.project_id,
        note=payload.note,
        mandatory=payload.mandatory,
        kind=payload.kind,
        case_sensitive=payload.case_sensitive,
        status=payload.status,
        reference=payload.reference,
        expand_on_first_use=payload.expand_on_first_use,
    )

    return GlossaryTermPublic.model_validate(term)


@router.patch("/glossary/{term_id}", response_model=GlossaryTermPublic)
async def update_glossary_term(
    term_id: uuid.UUID,
    payload: GlossaryTermUpdate,
    context: ContextDep,
    session: SessionDep,
) -> GlossaryTermPublic:
    """Поправить запись словаря.

    Этим живёт перепроверка: второй проход не заводит термины заново, он
    подтверждает, исправляет перевод и снимает дубликаты. Меняется только
    присланное — правка одного поля не должна затирать остальные.
    """
    term = await GlossaryService(session, context).update(
        term_id, payload.model_dump(exclude_unset=True)
    )

    return GlossaryTermPublic.model_validate(term)


@router.delete("/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    term_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> Response:
    await GlossaryService(session, context).delete(term_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
