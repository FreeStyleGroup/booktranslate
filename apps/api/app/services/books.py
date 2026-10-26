"""Издание книги и комплект её исходников.

Книга перестаёт быть одним файлом. У неё несколько источников с разными
ролями: из основного берут текст, по визуальному эталону сверяют вёрстку,
вспомогательные лежат рядом. Роль назначается явно — по формату её не
угадать: PDF бывает и единственным источником текста, и эталоном при
EPUB.

Всё здесь ограничено организацией из контекста: выборки строятся через
`scoped`, документ проверяется на принадлежность тому же проекту, что и
книга. Иначе файл одного заказчика попал бы в комплект другого.
"""

import enum
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError

from app.models.book import BookEdition, SourceValidationResult
from app.models.coding import CodeKind
from app.models.document import Document, SourceRole
from app.models.organization import Role
from app.models.project import Project
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.coding import CodeAllocator
from app.services.errors import ConflictError, NotFoundError
from app.services.source_validation import describe_mismatch

# Кто заводит книги и собирает комплект. Тот же набор, что у загрузки
# файлов: книга — это рамка вокруг загрузок, и разводить права между
# «завести книгу» и «положить в неё файл» значило бы запретить половину
# работы тому, кому разрешена вторая половина.
MANAGING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

# Приставка кода издания. Код уходит в номера замечаний
# (`BK01-CH03-ERR-0001`), поэтому выдаётся один раз и не меняется.
CODE_PREFIX = "BK"


class BookSort(str, enum.Enum):
    """По какому столбцу упорядочен список изданий.

    Перечислением, а не именем колонки из запроса: имя колонки пришлось бы
    сверять со списком разрешённых, а забытая сверка — это подстановка в
    `ORDER BY` снаружи.

    Сортировки по коду здесь нет намеренно. Код выдаётся по порядку, но
    это строка, и после сотой книги «BK100» встанет лексикографически
    раньше «BK99». Порядок заведения даёт `CREATED` и даёт верно.
    """

    CREATED = "created"
    TITLE = "title"
    UPDATED = "updated"


_SORT_COLUMNS = {
    BookSort.CREATED: BookEdition.created_at,
    BookSort.TITLE: BookEdition.title,
    BookSort.UPDATED: BookEdition.updated_at,
}


@dataclass(frozen=True, slots=True)
class SourceInKit:
    """Файл комплекта вместе с тем, что о нём удалось прочитать."""

    document: Document
    validation: SourceValidationResult | None


@dataclass(frozen=True, slots=True)
class BookKit:
    """Комплект исходников книги целиком.

    Предупреждение о разных изданиях лежит рядом с составом, а не
    считается отдельным запросом: оно выводится из тех же проверок, и
    второй поход в базу за теми же строками был бы лишним.
    """

    sources: list[SourceInKit]
    mismatch: str | None


@dataclass(frozen=True, slots=True)
class BookPage:
    """Страница списка изданий.

    Общее число — вместе со страницей: без него на экране нельзя показать
    ни «31 книга», ни номера страниц, а считать его вторым запросом с
    витрины значит сходить в базу дважды за одним списком.
    """

    total: int
    items: list[BookEdition]


class BookService(TenantService):
    async def create(
        self,
        *,
        project_id: uuid.UUID,
        title: str,
        author: str | None = None,
        edition_label: str | None = None,
    ) -> BookEdition:
        """Завести издание в проекте.

        Языковая пара берётся у проекта: книга переводится в той паре, для
        которой проект заведён, а спрашивать её второй раз значит дать
        возможность разойтись с глоссарием и памятью проекта.
        """
        self._context.require(*MANAGING_ROLES)

        project = await self._project(project_id)

        number = await CodeAllocator(self._session, self._context).next(
            CodeKind.BOOK, self.organization_id
        )

        book = BookEdition(
            organization_id=self.organization_id,
            project_id=project.id,
            code=f"{CODE_PREFIX}{number:02d}",
            title=title,
            author=author,
            edition_label=edition_label,
            source_language=project.source_language,
            target_language=project.target_language,
        )
        self._session.add(book)
        await self._session.flush()

        AuditService(self._session, self._context).record(
            kind="book.created",
            subject_type="book_edition",
            subject_id=book.id,
            payload={"code": book.code, "title": book.title},
        )

        await self._session.commit()
        await self._session.refresh(book)

        return book

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        sort: BookSort = BookSort.CREATED,
        descending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """Страница изданий с заданным порядком.

        Порядок задаёт запрос, а не браузер: отсортировать в браузере можно
        только выданную страницу, и тогда «по названию» означало бы «по
        названию среди этих пятидесяти» — то есть неправду.
        """
        statement = self.scoped(BookEdition)

        if project_id is not None:
            statement = statement.where(BookEdition.project_id == project_id)

        total = await self._count(statement)

        column = _SORT_COLUMNS[sort]
        rows = await self._session.scalars(
            statement
            # Второй столбец — чтобы порядок был однозначным: названия
            # повторяются, а страницы, выданные двумя запросами с разным
            # порядком одинаковых строк, покажут одну книгу дважды и
            # потеряют другую.
            .order_by(
                column.desc() if descending else column.asc(),
                BookEdition.id.desc() if descending else BookEdition.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )

        return BookPage(total=total, items=list(rows))

    async def _count(self, statement: Select[tuple[BookEdition]]) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )

        return int(counted or 0)

    async def get(self, book_id: uuid.UUID) -> BookEdition:
        """Издание своей организации.

        Чужое отдаётся как отсутствующее, а не как запрещённое: «403»
        подтвердил бы, что такой идентификатор существует.
        """
        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))

        if book is None:
            raise NotFoundError("Книга не найдена")

        return book

    async def kit(self, book_id: uuid.UUID) -> BookKit:
        """Комплект исходников книги и предупреждение о разных изданиях.

        Порядок — по роли и дате: основной источник первым, чтобы на
        экране он не терялся среди вспомогательных.
        """
        book = await self.get(book_id)

        documents = list(
            await self._session.scalars(
                self.scoped(Document)
                .where(Document.book_id == book.id)
                .order_by(Document.source_role, Document.created_at)
            )
        )

        validations = await self._validations([document.id for document in documents])
        sources = [
            SourceInKit(document=document, validation=validations.get(document.id))
            for document in documents
        ]

        return BookKit(sources=sources, mismatch=_mismatch_of(sources))

    async def attach(
        self, *, book_id: uuid.UUID, document_id: uuid.UUID, role: SourceRole
    ) -> Document:
        """Включить загруженный файл в комплект книги с ролью."""
        self._context.require(*MANAGING_ROLES)

        book = await self.get(book_id)
        document = await self._document(document_id)

        if document.project_id != book.project_id:
            raise ConflictError("Файл загружен в другой проект")

        if document.book_id is not None and document.book_id != book.id:
            raise ConflictError("Файл уже входит в комплект другой книги")

        document.book_id = book.id

        return await self._apply_role(document, role, book_id=book.id)

    async def set_role(
        self, *, book_id: uuid.UUID, document_id: uuid.UUID, role: SourceRole
    ) -> Document:
        """Сменить роль файла, уже входящего в комплект.

        Заменить основной источник можно только так: сперва прежнему
        назначают другую роль, потом новому — основную. Два осознанных
        действия вместо одного случайного.
        """
        self._context.require(*MANAGING_ROLES)

        document = await self.source(book_id=book_id, document_id=document_id)

        return await self._apply_role(document, role, book_id=book_id)

    async def check_can_attach(
        self, *, book_id: uuid.UUID, project_id: uuid.UUID, role: SourceRole
    ) -> BookEdition:
        """Можно ли будет включить в комплект файл этого проекта с этой ролью.

        Спрашивается до того, как файл посчитан и уложен в хранилище:
        проделать это со стомегабайтной книгой и затем отказать — значит
        взять работу и выбросить её вместе с ожиданием человека.

        Решение она не подменяет: включение всё равно проходит через
        `attach`, и там же стоит ограничение базы. Здесь — только то, что
        видно заранее.
        """
        book = await self.get(book_id)

        if book.project_id != project_id:
            raise ConflictError("Книга заведена в другом проекте")

        if role is SourceRole.PRIMARY_TEXT:
            taken = await self._session.scalar(
                self.scoped(Document).where(
                    Document.book_id == book.id,
                    Document.source_role == SourceRole.PRIMARY_TEXT,
                )
            )

            if taken is not None:
                raise ConflictError(
                    "У книги уже есть основной источник текста. "
                    "Чтобы заменить его, сначала назначьте прежнему другую роль"
                )

        return book

    async def source(self, *, book_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        """Файл из комплекта этой книги.

        Отдельным методом, потому что проверку просят трое: смена роли,
        запуск проверки файла и выдача его сведений. Разойдясь, они дали
        бы разный ответ на один вопрос.
        """
        book = await self.get(book_id)
        document = await self._document(document_id)

        if document.book_id != book.id:
            raise ConflictError("Файл не входит в комплект этой книги")

        return document

    async def _apply_role(
        self, document: Document, role: SourceRole, *, book_id: uuid.UUID
    ) -> Document:
        """Назначить роль и сохранить, отличив повтор от настоящей ошибки."""
        previous = document.source_role
        document.source_role = role

        AuditService(self._session, self._context).record(
            kind="book.source_role_set",
            subject_type="document",
            subject_id=document.id,
            payload={
                "book_id": str(book_id),
                "role": role.name,
                "previous_role": previous.name if previous is not None else None,
            },
        )

        try:
            await self._session.commit()
        except IntegrityError:
            # У издания один основной источник; ограничение стоит в базе.
            # Две одновременные загрузки проходят проверку обе, и отличить
            # повтор от настоящей ошибки можно только здесь.
            await self._session.rollback()

            if role is not SourceRole.PRIMARY_TEXT:
                raise

            raise ConflictError(
                "У книги уже есть основной источник текста. "
                "Чтобы заменить его, сначала назначьте прежнему другую роль"
            ) from None

        await self._session.refresh(document)

        return document

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self._session.scalar(self.scoped(Project).where(Project.id == project_id))

        if project is None:
            raise NotFoundError("Проект не найден")

        return project

    async def _document(self, document_id: uuid.UUID) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )

        if document is None:
            raise NotFoundError("Файл не найден")

        return document

    async def _validations(
        self,
        # Sequence, а не list: в теле класса имя `list` занято методом
        # `list()`, и аннотация вычислилась бы как обращение к нему.
        # Заодно подпись честнее — функции достаточно последовательности.
        document_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, SourceValidationResult]:
        results = await self._session.scalars(
            self.scoped(SourceValidationResult).where(
                SourceValidationResult.document_id.in_(document_ids)
            )
        )

        return {result.document_id: result for result in results}


def _mismatch_of(sources: list[SourceInKit]) -> str | None:
    """Первое расхождение между основным источником и остальными.

    Сравнивать есть что только при основном источнике: без него неизвестно,
    с чем сверять. Первое найденное расхождение и возвращается — человеку
    нужен повод открыть файлы, а не полный список отличий.
    """
    primary = next(
        (
            source
            for source in sources
            if source.document.source_role is SourceRole.PRIMARY_TEXT
            and source.validation is not None
        ),
        None,
    )

    if primary is None or primary.validation is None:
        return None

    for source in sources:
        if source.document.id == primary.document.id or source.validation is None:
            continue

        mismatch = describe_mismatch(primary.validation, source.validation)
        if mismatch is not None:
            return mismatch

    return None
