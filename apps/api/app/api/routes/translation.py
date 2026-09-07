"""Перевод документа и словарь терминов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContextDep, ProviderDep, SessionDep
from app.schemas.glossary import GlossaryTermCreate, GlossaryTermPublic, TranslationResult
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
) -> TranslationResult:
    """Перевести сегменты документа.

    По умолчанию берутся только непереведённые: повторный запуск не трогает
    правку человека. Ответ — не список сегментов, а сводка: их могут быть
    десятки тысяч, а по сводке видно, сколько закрыто памятью и сколько
    пришлось отдать модели.
    """
    summary = await TranslationService(session, context, provider).translate(
        document_id, force=force
    )

    return TranslationResult(
        total=summary.total,
        from_memory=summary.from_memory,
        from_provider=summary.from_provider,
        flagged=summary.flagged,
        unique_texts=summary.unique_texts,
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
    )

    return GlossaryTermPublic.model_validate(term)


@router.delete("/glossary/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    term_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> Response:
    await GlossaryService(session, context).delete(term_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
