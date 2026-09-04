"""Загрузка, просмотр и выдача документов."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.schemas.document import DocumentPublic
from app.services.documents import DocumentService
from app.services.formats import media_type
from app.services.storage import CHUNK_BYTES

router = APIRouter(tags=["documents"])


async def _chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    """Содержимое загрузки кусками.

    Файл читается порциями, а не целиком: руководство на восемьсот страниц
    в памяти процесса — это отказ сервера при нескольких одновременных
    загрузках.
    """
    while chunk := await upload.read(CHUNK_BYTES):
        yield chunk


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
        stream=_chunks(file),
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


@router.get("/documents/{document_id}", response_model=DocumentPublic)
async def get_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> DocumentPublic:
    document = await DocumentService(session, context, storage).get(document_id)

    return DocumentPublic.model_validate(document)


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


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> Response:
    await DocumentService(session, context, storage).delete(document_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
