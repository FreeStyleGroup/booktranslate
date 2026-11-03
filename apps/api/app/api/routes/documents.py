"""Загрузка, просмотр и выдача документов."""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.api.uploads import chunks
from app.models.document import SourceFormat, SourceRole
from app.schemas.document import DocumentPublic
from app.services.documents import DocumentService
from app.services.errors import InvalidInputError
from app.services.formats import media_type

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
    book_id: Annotated[uuid.UUID | None, Form(description="Включить в комплект этой книги")] = None,
    source_role: Annotated[SourceRole | None, Form(description="Роль файла в комплекте")] = None,
) -> DocumentPublic:
    """Принять файл в проект.

    Повторная загрузка того же файла отдаёт уже заведённый документ с кодом
    200 вместо 201: клиент по коду отличает новую загрузку от повтора, а
    платить за второй разбор и перевод одинакового содержимого незачем.

    `book_id` и `source_role` задаются вместе и включают принятый файл в
    комплект книги тем же запросом. Порознь они не имеют смысла: роль
    описывает место файла в комплекте, а комплект — у книги.
    """
    document, created = await DocumentService(session, context, storage).upload(
        project_id=project_id,
        filename=file.filename or "document",
        stream=chunks(file),
        title=title,
        book_id=book_id,
        source_role=source_role,
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


@router.get("/documents/{document_id}/content")
async def download_document(
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
    view: Annotated[
        bool, Query(description="Открыть PDF для просмотра в браузере, а не скачать")
    ] = False,
) -> StreamingResponse:
    """Исходный файл — скачать или, если это PDF, посмотреть в браузере.

    Просмотр — только для PDF. Его просят ради визуального эталона: мастер
    главы сверяют со страницей вёрстки. Любой другой формат отдаётся только
    на скачивание: HTML или SVG, загруженный заказчиком и открытый с домена
    сервиса, выполнил бы свои скрипты от имени сервиса.
    """
    service = DocumentService(session, context, storage)
    document = await service.get(document_id)

    if view and document.source_format is not SourceFormat.PDF:
        raise InvalidInputError("Посмотреть в браузере можно только PDF — остальное скачивается")

    # filename* с процентным кодированием: имена файлов бывают русскими, а
    # в обычном filename за пределы latin-1 выходить нельзя.
    name = quote(document.original_filename or document.title)
    disposition = "inline" if view else "attachment"

    return StreamingResponse(
        service.stream(document),
        media_type=media_type(document.source_format),
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{name}",
            # Тип файла — тот, что объявлен, а не угаданный браузером по
            # содержимому: угадывание и превращает «картинку» в страницу.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> Response:
    await DocumentService(session, context, storage).delete(document_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
