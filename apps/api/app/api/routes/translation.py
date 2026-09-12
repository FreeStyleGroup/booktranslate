"""Перевод документа и словарь терминов."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import ContextDep, ProviderDep, SessionDep
from app.api.uploads import read_capped
from app.core.config import get_settings
from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.schemas.glossary import (
    GlossaryPagePublic,
    GlossaryTermCreate,
    GlossaryTermPublic,
    GlossaryTermUpdate,
    TranslationResult,
)
from app.schemas.shared import (
    DictionaryImportResult,
    GlossaryUploadPublic,
    SharedTermPublic,
    SuggestionsPublic,
)
from app.services.dictionaries import read_dictionary
from app.services.glossary import MAX_REASONS, GlossaryService
from app.services.pricing import estimate_usd
from app.services.shared_glossary import SuggestionService
from app.services.translation import TranslationService

router = APIRouter(tags=["translation"])


@router.post("/documents/{document_id}/translate", response_model=TranslationResult)
async def translate_document(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    provider: ProviderDep,
    limit: Annotated[
        int | None,
        Query(
            description=(
                "Сколько непереведённых сегментов взять этим вызовом. Без значения — "
                "TRANSLATION_DEFAULT_LIMIT, не больше TRANSLATION_MAX_SEGMENTS_PER_RUN"
            )
        ),
    ] = None,
    force: Annotated[
        bool,
        Query(
            description=(
                "На документе без непереведённых сегментов — перевести заново, включая "
                "отредактированные и принятые; на документе с непереведёнными — продолжить; "
                "на зависшем в «переводится» дольше TRANSLATION_STALE_MINUTES — снять "
                "отметку и продолжить"
            )
        ),
    ] = False,
    ignore_terminology: Annotated[
        bool,
        Query(description="Переводить, не дожидаясь решений по кандидатам в словарь"),
    ] = False,
) -> TranslationResult:
    """Перевести очередную порцию сегментов документа.

    Один вызов берёт `limit` непереведённых сегментов в порядке книги и
    отвечает, сколько осталось (`remaining`); книга переводится циклом
    вызовов до нуля. Так задумано: обратный прокси режет соединение через
    четверть часа, а сделанное до срыва фиксируется по пачкам и не
    теряется. Повторный вызов не трогает правку человека: берутся только
    непереведённые.

    Ответ — не список сегментов, а сводка: их могут быть десятки тысяч, а
    по сводке видно, сколько закрыто памятью и сколько пришлось отдать
    модели.

    Незаконченный терминологический проход останавливает перевод: словарь,
    решённый наполовину, даёт в книге два названия для одной вещи. Обойти
    это можно (`ignore_terminology`), но это осознанный шаг, а не умолчание.
    """
    summary = await TranslationService(session, context, provider).translate(
        document_id, limit=limit, force=force, ignore_terminology=ignore_terminology
    )

    return TranslationResult(
        total=summary.total,
        from_memory=summary.from_memory,
        from_provider=summary.from_provider,
        flagged=summary.flagged,
        unique_texts=summary.unique_texts,
        provider_calls=summary.provider_calls,
        saved_calls=summary.saved_calls,
        remaining=summary.remaining,
        status=summary.status,
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


@router.get("/glossary", response_model=GlossaryPagePublic)
async def list_glossary(
    context: ContextDep,
    session: SessionDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    query: Annotated[
        str | None, Query(max_length=300, description="Часть термина или перевода")
    ] = None,
    kind: Annotated[GlossaryEntryKind | None, Query()] = None,
    status_filter: Annotated[GlossaryTermStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GlossaryPagePublic:
    """Словарь пространства страницей, с отбором по слову, разряду и состоянию."""
    page = await GlossaryService(session, context).list(
        project_id=project_id,
        query=query,
        kind=kind,
        status=status_filter,
        limit=limit,
        offset=offset,
    )

    return GlossaryPagePublic(
        total=page.total, items=[GlossaryTermPublic.model_validate(term) for term in page.items]
    )


@router.get("/glossary/uploads", response_model=list[GlossaryUploadPublic])
async def list_glossary_uploads(
    context: ContextDep, session: SessionDep
) -> list[GlossaryUploadPublic]:
    """Что загружали в словарь: последние первыми."""
    uploads = await GlossaryService(session, context).uploads()

    return [GlossaryUploadPublic.model_validate(upload) for upload in uploads]


@router.get("/glossary/suggestions", response_model=SuggestionsPublic)
async def list_glossary_suggestions(context: ContextDep, session: SessionDep) -> SuggestionsPublic:
    """Подсказки из общего словаря площадки по тематике пространства.

    Только то, чего в своём словаре нет: своё решение подсказку снимает.
    Без тематики список пуст — и ответ говорит об этом, а не молчит.
    """
    suggestions = await SuggestionService(session, context).suggest()

    return SuggestionsPublic(
        subject=suggestions.subject,
        items=[SharedTermPublic.model_validate(item) for item in suggestions.items],
    )


@router.post(
    "/glossary/suggestions/{shared_id}",
    response_model=GlossaryTermPublic,
    status_code=status.HTTP_201_CREATED,
)
async def accept_glossary_suggestion(
    shared_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> GlossaryTermPublic:
    """Принять подсказку: она становится своим подтверждённым термином."""
    term = await SuggestionService(session, context).accept(shared_id)

    return GlossaryTermPublic.model_validate(term)


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
    share: Annotated[
        bool | None,
        Form(
            description=(
                "Разрешить площадке взять термины этой загрузки в общий словарь. Не "
                "передано — по настройке пространства; иное значение меняет настройку и "
                "требует прав администратора пространства"
            )
        ),
    ] = None,
) -> DictionaryImportResult:
    """Загрузить словарь из файла.

    Заведённое человеком не перезаписывается: тот, кто правил термин, знает
    про эту книгу больше, чем чужая база на двадцать тысяч строк. Такие
    записи попадают в пропущенные с причиной, а не молча теряются.

    Ответ — сводка, а не список: по числу добавленных и причинам пропуска
    сразу видно, тот ли файл загрузили и не перепутаны ли колонки местами.
    """
    filename = file.filename or ""
    contents = read_dictionary(
        # Не `file.read()`: он берёт в память столько, сколько принесли, и
        # многогигабайтный «словарь» кладёт процесс раньше, чем дело дойдёт
        # до разбора.
        await read_capped(file, limit_bytes=get_settings().max_upload_bytes),
        filename,
        source_language=source_language,
        target_language=target_language,
    )

    report = await GlossaryService(session, context).import_terms(
        contents.terms,
        source_language=source_language,
        target_language=target_language,
        project_id=project_id,
        origin=origin,
        filename=filename,
        overwrite_manual=overwrite_manual,
        share=share,
        unreadable=len(contents.skipped),
    )
    assert report.upload is not None  # noqa: S101 — загрузка записывается всегда

    # Причины из разбора файла и из записи в базу — это одно и то же для
    # того, кто загружает: он хочет видеть, что не доехало, а не где именно
    # оно потерялось.
    return DictionaryImportResult(
        total=report.total + len(contents.skipped),
        added=report.added,
        updated=report.updated,
        skipped=report.skipped + len(contents.skipped),
        reasons=[*contents.skipped[:MAX_REASONS], *report.reasons][:MAX_REASONS],
        upload=GlossaryUploadPublic.model_validate(report.upload),
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
