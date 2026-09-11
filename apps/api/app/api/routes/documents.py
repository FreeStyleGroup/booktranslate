"""Загрузка, просмотр и выдача документов."""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.api.uploads import chunks
from app.core.config import get_settings
from app.schemas.document import DocumentProfilePublic, DocumentPublic
from app.services.documents import DocumentService
from app.services.export import ExportFormat
from app.services.exporting import ExportService
from app.services.formats import media_type
from app.services.profiling import ProfilingService
from app.services.providers import provider_name

router = APIRouter(tags=["documents"])


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentPublic,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    project_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    response: Response,
    file: Annotated[UploadFile, File(description="Исходный файл документа")],
    title: Annotated[str | None, Form(max_length=500)] = None,
) -> DocumentPublic:
    """Принять файл в проект.

    Повторная загрузка того же файла отдаёт уже заведённый документ с кодом
    200 вместо 201: клиент по коду отличает новую загрузку от повтора, а
    платить за второй разбор и перевод одинакового содержимого незачем.
    """
    document, created = await DocumentService(session, context, storage).upload(
        project_id=project_id,
        filename=file.filename or "document",
        stream=chunks(file),
        title=title,
    )

    if not created:
        response.status_code = status.HTTP_200_OK

    return DocumentPublic.model_validate(document)


@router.get("/projects/{project_id}/documents", response_model=list[DocumentPublic])
async def list_documents(
    project_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentPublic]:
    documents = await DocumentService(session, context, storage).list(
        project_id=project_id, limit=limit, offset=offset
    )

    return [DocumentPublic.model_validate(document) for document in documents]


@router.get("/documents", response_model=list[DocumentPublic])
async def list_all_documents(
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    project_id: Annotated[
        uuid.UUID | None, Query(description="Только документы этого проекта")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentPublic]:
    """Документы рабочего пространства — всех проектов сразу.

    Отдельно от списка по проекту, потому что вопрос другой: «что у нас
    сейчас в работе» человек задаёт раньше, чем выбирает проект, и
    собирать ответ обходом проектов значило бы делать по запросу на
    каждый.
    """
    documents = await DocumentService(session, context, storage).list_all(
        project_id=project_id, limit=limit, offset=offset
    )

    return [DocumentPublic.model_validate(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentPublic)
async def get_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> DocumentPublic:
    document = await DocumentService(session, context, storage).get(document_id)

    return DocumentPublic.model_validate(document)


@router.get("/documents/{document_id}/profile", response_model=DocumentProfilePublic)
async def document_profile(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
) -> DocumentProfilePublic:
    """Из чего состоит документ и во что обойдётся его перевод.

    Считается по сегментам, поэтому до разбора отвечает нулями — это не
    ошибка, а честный ответ: пока файл не разобран, про его состав ничего
    не известно, кроме размера в байтах.

    Смета — оценка сверху и помечена как оценка. Она нужна до перевода:
    узнать цену книги, запустив перевод, можно и так, но платить за это
    придётся уже по-настоящему.
    """
    profile = await ProfilingService(session, context).build(
        document_id,
        model=provider_name(),
        context_segments=get_settings().translation_context_segments,
    )

    return DocumentProfilePublic.model_validate(profile)


@router.get("/documents/{document_id}/content")
async def download_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> StreamingResponse:
    service = DocumentService(session, context, storage)
    document = await service.get(document_id)

    # filename* с процентным кодированием: имена файлов бывают русскими, а
    # в обычном filename за пределы latin-1 выходить нельзя.
    name = quote(document.original_filename or document.title)

    return StreamingResponse(
        service.stream(document),
        media_type=media_type(document.source_format),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )


@router.get("/documents/{document_id}/export")
async def export_document(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    export_format: Annotated[
        ExportFormat,
        Query(alias="format", description="Формат выгрузки; source — как приносили"),
    ] = ExportFormat.SOURCE,
    allow_untranslated: Annotated[
        bool,
        Query(description="Выгрузить черновик: непереведённое уйдёт исходным текстом"),
    ] = False,
) -> Response:
    """Забрать перевод файлом.

    По умолчанию собирается в формате оригинала и только целиком:
    недопереведённая книга, отданная молча, — худшее, что здесь можно
    сделать, потому что заметят это позже всех. Черновик доступен явным
    разрешением, и тогда число непереведённых блоков возвращается заголовком
    `X-Untranslated-Blocks`.
    """
    result = await ExportService(session, context, storage).export(
        document_id, export_format=export_format, allow_untranslated=allow_untranslated
    )

    # filename* с процентным кодированием: имя собирается из названия
    # документа, а оно бывает русским.
    name = quote(result.filename)

    return Response(
        content=result.rendered.content,
        media_type=result.rendered.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{name}",
            "X-Untranslated-Blocks": str(result.untranslated),
        },
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> Response:
    await DocumentService(session, context, storage).delete(document_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
