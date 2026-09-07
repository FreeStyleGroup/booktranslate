"""Перевод документа и словарь терминов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import ContextDep, ProviderDep, SessionDep
from app.api.uploads import read_capped
from app.core.config import get_settings
from app.schemas.glossary import (
    DictionaryImportResult,
    GlossaryTermCreate,
    GlossaryTermPublic,
    GlossaryTermUpdate,
    TranslationResult,
)
from app.services.dictionaries import read_dictionary
from app.services.glossary import MAX_REASONS, GlossaryService
from app.services.pricing import estimate_usd
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
        input_tokens=summary.usage.input_tokens,
        output_tokens=summary.usage.output_tokens,
        cached_input_tokens=summary.usage.cached_input_tokens,
        cache_write_tokens=summary.usage.cache_write_tokens,
        estimated_usd=estimate_usd(
            provider.name,
            input_tokens=summary.usage.input_tokens,
            output_tokens=summary.usage.output_tokens,
            cached_input_tokens=summary.usage.cached_input_tokens,
            cache_write_tokens=summary.usage.cache_write_tokens,
        ),
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


@router.post("/glossary/import", response_model=DictionaryImportResult)
async def import_glossary(
    context: ContextDep,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="CSV, TSV, TBX или реестр в DOCX")],
    source_language: Annotated[str, Form(min_length=2, max_length=10)],
    target_language: Annotated[str, Form(min_length=2, max_length=10)],
    project_id: Annotated[uuid.UUID | None, Form()] = None,
    origin: Annotated[
        str, Form(max_length=100, description="Откуда словарь: имя базы или заказчика")
    ] = "файл",
    overwrite_manual: Annotated[
        bool, Form(description="Перезаписывать записи, заведённые вручную")
    ] = False,
) -> DictionaryImportResult:
    """Загрузить словарь из файла.

    Заведённое человеком не перезаписывается: тот, кто правил термин, знает
    про эту книгу больше, чем чужая база на двадцать тысяч строк. Такие
    записи попадают в пропущенные с причиной, а не молча теряются.

    Ответ — сводка, а не список: по числу добавленных и причинам пропуска
    сразу видно, тот ли файл загрузили и не перепутаны ли колонки местами.
    """
    contents = read_dictionary(
        # Не `file.read()`: он берёт в память столько, сколько принесли, и
        # многогигабайтный «словарь» кладёт процесс раньше, чем дело дойдёт
        # до разбора.
        await read_capped(file, limit_bytes=get_settings().max_upload_bytes),
        file.filename or "",
        source_language=source_language,
        target_language=target_language,
    )

    report = await GlossaryService(session, context).import_terms(
        contents.terms,
        source_language=source_language,
        target_language=target_language,
        project_id=project_id,
        source=f"import:{origin}",
        overwrite_manual=overwrite_manual,
    )

    # Причины из разбора файла и из записи в базу — это одно и то же для
    # того, кто загружает: он хочет видеть, что не доехало, а не где именно
    # оно потерялось.
    return DictionaryImportResult(
        total=report.total + len(contents.skipped),
        added=report.added,
        updated=report.updated,
        skipped=report.skipped + len(contents.skipped),
        reasons=[*contents.skipped[:MAX_REASONS], *report.reasons][:MAX_REASONS],
    )


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
