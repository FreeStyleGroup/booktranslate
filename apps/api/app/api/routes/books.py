"""Издания и комплект исходников книги."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.schemas.book import (
    BookCreate,
    BookKitPublic,
    BookPagePublic,
    BookPublic,
    SourceAttach,
    SourcePublic,
    SourceRoleUpdate,
    ValidationPublic,
)
from app.schemas.paging import SortOrder
from app.services.books import BookPage, BookService, BookSort, SourceInKit
from app.services.source_validation import SourceValidationService

router = APIRouter(tags=["books"])


@router.post(
    "/projects/{project_id}/books", response_model=BookPublic, status_code=status.HTTP_201_CREATED
)
async def create_book(
    project_id: uuid.UUID, payload: BookCreate, context: ContextDep, session: SessionDep
) -> BookPublic:
    """Завести книгу в проекте.

    Языковая пара берётся у проекта: книга переводится в той паре, для
    которой проект заведён. Код издания (`BK01`) выдаёт сервер — он уходит
    в номера замечаний и потому не задаётся снаружи.
    """
    book = await BookService(session, context).create(
        project_id=project_id,
        title=payload.title,
        author=payload.author,
        edition_label=payload.edition_label,
    )

    return BookPublic.model_validate(book)


@router.get("/projects/{project_id}/books", response_model=BookPagePublic)
async def list_project_books(
    project_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    sort: BookSort = BookSort.CODE,
    order: SortOrder = SortOrder.DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookPagePublic:
    page = await BookService(session, context).list(
        project_id=project_id,
        sort=sort,
        descending=order is SortOrder.DESC,
        limit=limit,
        offset=offset,
    )

    return _page(page, limit=limit, offset=offset)


@router.get("/books", response_model=BookPagePublic)
async def list_books(
    context: ContextDep,
    session: SessionDep,
    sort: BookSort = BookSort.CODE,
    order: SortOrder = SortOrder.DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookPagePublic:
    """Издания пространства.

    Порядок и страница задаются запросом: книг у заказчика бывают сотни, и
    упорядочить их в браузере можно только внутри выданной страницы — то
    есть показать «по названию» то, что по названию не отобрано.
    """
    page = await BookService(session, context).list(
        sort=sort, descending=order is SortOrder.DESC, limit=limit, offset=offset
    )

    return _page(page, limit=limit, offset=offset)


@router.get("/books/{book_id}", response_model=BookPublic)
async def get_book(book_id: uuid.UUID, context: ContextDep, session: SessionDep) -> BookPublic:
    book = await BookService(session, context).get(book_id)

    return BookPublic.model_validate(book)


@router.get("/books/{book_id}/sources", response_model=BookKitPublic)
async def book_sources(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BookKitPublic:
    """Комплект исходников: файлы, их роли и результат проверки.

    Рядом с составом — предупреждение, если источники похожи на разные
    издания. Это именно предупреждение: решение принимает человек.
    """
    kit = await BookService(session, context).kit(book_id)

    return BookKitPublic(sources=[_source(source) for source in kit.sources], mismatch=kit.mismatch)


@router.post(
    "/books/{book_id}/sources", response_model=SourcePublic, status_code=status.HTTP_201_CREATED
)
async def attach_source(
    book_id: uuid.UUID, payload: SourceAttach, context: ContextDep, session: SessionDep
) -> SourcePublic:
    """Включить загруженный файл в комплект книги с ролью.

    Роль назначается явно: по формату её не угадать — PDF бывает и
    единственным источником текста, и визуальным эталоном при EPUB.
    """
    document = await BookService(session, context).attach(
        book_id=book_id, document_id=payload.document_id, role=payload.role
    )

    return SourcePublic.model_validate(document)


@router.patch("/books/{book_id}/sources/{document_id}", response_model=SourcePublic)
async def change_source_role(
    book_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: SourceRoleUpdate,
    context: ContextDep,
    session: SessionDep,
) -> SourcePublic:
    """Сменить роль файла в комплекте.

    Основной источник у книги один. Чтобы заменить его, сперва назначьте
    прежнему другую роль: два осознанных действия вместо одного
    случайного.
    """
    document = await BookService(session, context).set_role(
        book_id=book_id, document_id=document_id, role=payload.role
    )

    return SourcePublic.model_validate(document)


@router.post("/books/{book_id}/sources/{document_id}/validation", response_model=ValidationPublic)
async def validate_source(
    book_id: uuid.UUID,
    document_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    storage: StorageDep,
) -> ValidationPublic:
    """Проверить файл: читается ли формат, есть ли текст, что он о себе заявляет.

    Отдельным действием, а не на загрузке: на книге в тысячу страниц
    чтение занимает время, и держать его внутри запроса на приём файла
    значит заставлять человека ждать молча.
    """
    books = BookService(session, context)
    document = await books.source(book_id=book_id, document_id=document_id)

    result = await SourceValidationService(session, context, storage).validate(document.id)

    return ValidationPublic.model_validate(result)


def _page(page: BookPage, *, limit: int, offset: int) -> BookPagePublic:
    return BookPagePublic(
        total=page.total,
        limit=limit,
        offset=offset,
        items=[BookPublic.model_validate(book) for book in page.items],
    )


def _source(source: SourceInKit) -> SourcePublic:
    """Строка комплекта: файл и то, что о нём известно."""
    validation = (
        ValidationPublic.model_validate(source.validation)
        if source.validation is not None
        else None
    )

    # `model_copy` с обновлением, а не присваивание полю: собранная схема
    # не должна меняться после проверки — иначе однажды в неё допишут
    # значение, которое проверку не проходило.
    return SourcePublic.model_validate(source.document).model_copy(
        update={"validation": validation}
    )
