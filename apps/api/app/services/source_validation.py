"""Что сервис смог прочитать в загруженном файле.

Проверка нужна человеку до начала работы, а не через час на пустом
разборе: PDF без текстового слоя переводить нечем, а EPUB и PDF из разных
изданий дадут главы, которые не сойдутся по нумерации.

Проверка не разбирает книгу целиком. Чтобы ответить «текст есть», хватает
первых блоков; число страниц и метаданные читаются по служебным частям
файла, а не по его содержимому. Полный разбор стоит дорого и делается
один раз, когда книга уже собрана.
"""

import asyncio
import re
import uuid
import zipfile
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

import docx
from defusedxml.common import DefusedXmlException
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import PDFException
from pdfminer.psparser import PSException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import SourceValidationResult
from app.models.document import Document, SourceFormat
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import NotFoundError
from app.services.parsers import PARSER_VERSION, ParsingError, parser_for
from app.services.parsers.archives import ArchiveTooLargeError, check_archive
from app.services.parsers.markup import read_opf
from app.services.source_files import local_copy
from app.services.storage import ObjectStorage

# Сколько блоков читать, чтобы ответить на вопрос «текст в файле есть».
# Первый блок бывает пустым заголовком или колонтитулом, поэтому не один.
PROBE_BLOCKS = 5

# Разделители и знаки, по которым названия отличаются, не отличаясь по
# сути: «Machine Learning: a Guide» и «Machine Learning — a Guide».
_NOISE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class FileFacts:
    """Сведения, прочитанные из файла, без обращения к базе."""

    format_ok: bool
    has_text_layer: bool
    page_count: int | None = None
    title: str | None = None
    author: str | None = None
    # Кортеж, а не список: запись неизменяемая, и менять её содержимое на
    # месте не должно быть возможно.
    warnings: tuple[str, ...] = ()


def read_facts(path: Path, source_format: SourceFormat) -> FileFacts:
    """Прочитать файл и ответить, годится ли он в источник.

    Функция чистая: на входе путь и формат, на выходе сведения. Так её
    можно проверить на настоящих файлах без базы и без FastAPI.
    """
    parser = parser_for(source_format)

    if parser is None:
        return FileFacts(
            format_ok=False,
            has_text_layer=False,
            warnings=(f"Формат {source_format.value} пока не разбирается",),
        )

    warnings: list[str] = []

    try:
        blocks = list(islice(parser.parse(path), PROBE_BLOCKS))
        has_text = any(block.text.strip() for block in blocks)
    except ParsingError as error:
        # Разборщик открыл файл и сказал, чего в нём нет: у PDF это
        # «текстового слоя нет, это скан». Формат при этом читается —
        # «не читается» оставлено для файла, который не открылся вовсе.
        return FileFacts(format_ok=True, has_text_layer=False, warnings=(str(error),))
    except (OSError, zipfile.BadZipFile, ArchiveTooLargeError) as error:
        return FileFacts(format_ok=False, has_text_layer=False, warnings=(str(error),))

    if not has_text:
        warnings.append("В файле не нашлось текста")

    page_count, title, author, meta_warnings = _metadata(path, source_format)
    warnings.extend(meta_warnings)

    return FileFacts(
        format_ok=True,
        has_text_layer=has_text,
        page_count=page_count,
        title=title,
        author=author,
        warnings=tuple(warnings),
    )


def describe_mismatch(primary: SourceValidationResult, other: SourceValidationResult) -> str | None:
    """Похоже ли, что два источника — разные издания одной книги.

    Сравниваются название и автор, объявленные самими файлами. Число
    страниц для этого не годится: у EPUB страниц нет вовсе, а у PDF их
    число зависит от вёрстки издания.

    Ответ — предупреждение, а не запрет: у правильного комплекта названия
    тоже расходятся (перевод, подзаголовок, серия), и решение принимает
    человек.
    """
    if _differs(primary.meta_title, other.meta_title):
        return (
            f"Источники называются по-разному: «{primary.meta_title}» и "
            f"«{other.meta_title}». Проверьте, что это одно издание"
        )

    if _differs(primary.meta_author, other.meta_author):
        return (
            f"У источников разные авторы: «{primary.meta_author}» и "
            f"«{other.meta_author}». Проверьте, что это одна книга"
        )

    return None


class SourceValidationService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def validate(self, document_id: uuid.UUID) -> SourceValidationResult:
        """Проверить файл и сохранить результат.

        Запись у документа одна: файл неизменяем — повторная загрузка
        заводит новый документ, — поэтому перепроверка обновляет прежнюю
        запись, а не копит историю проверок одного и того же.
        """
        document = await self._document(document_id)
        facts = await self._read(document)

        result = await self._session.scalar(
            self.scoped(SourceValidationResult).where(
                SourceValidationResult.document_id == document.id
            )
        )

        if result is None:
            result = SourceValidationResult(
                organization_id=self.organization_id, document_id=document.id
            )
            self._session.add(result)

        result.format_ok = facts.format_ok
        result.has_text_layer = facts.has_text_layer
        result.page_count = facts.page_count
        result.meta_title = facts.title
        result.meta_author = facts.author
        result.parser_version = PARSER_VERSION
        result.warnings = list(facts.warnings)

        await self._session.commit()
        await self._session.refresh(result)

        return result

    async def _read(self, document: Document) -> FileFacts:
        """Забрать файл из хранилища во временную копию и прочитать сведения."""
        async with local_copy(self._storage, document.storage_key) as path:
            # Чтение файла — блокирующая работа с диском. В потоке событий
            # она остановила бы обслуживание остальных запросов.
            return await asyncio.to_thread(read_facts, path, document.source_format)

    async def _document(self, document_id: uuid.UUID) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )

        if document is None:
            raise NotFoundError("Файл не найден")

        return document


def _metadata(
    path: Path, source_format: SourceFormat
) -> tuple[int | None, str | None, str | None, list[str]]:
    """Число страниц, название и автор так, как их объявляет сам файл."""
    if source_format is SourceFormat.PDF:
        return _pdf_metadata(path)

    if source_format is SourceFormat.EPUB:
        title, author = _epub_metadata(path)
        return None, title, author, []

    if source_format is SourceFormat.DOCX:
        title, author = _docx_metadata(path)
        return None, title, author, []

    # У простого текста и разметки объявленных сведений нет: название в
    # них — первая строка, а это догадка, а не метаданные.
    return None, None, None, []


def _pdf_metadata(path: Path) -> tuple[int | None, str | None, str | None, list[str]]:
    try:
        with path.open("rb") as handle:
            document = PDFDocument(PDFParser(handle))
            pages = sum(1 for _ in PDFPage.create_pages(document))
            info = document.info[0] if document.info else {}

            return pages, _pdf_text(info.get("Title")), _pdf_text(info.get("Author")), []
    except (PSException, PDFException, OSError) as error:
        # Сведения не прочитались, но текст из файла до этого достался:
        # это повод для замечания, а не для отказа в источнике.
        return None, None, None, [f"Сведения PDF не читаются: {error}"]


def _pdf_text(value: object) -> str | None:
    """Строка из словаря сведений PDF.

    Значения там байтовые: либо UTF-16 с меткой порядка байтов, либо
    однобайтовая кодировка PDFDocEncoding, которая на печатных знаках
    совпадает с latin-1.
    """
    if not isinstance(value, bytes):
        return None

    if value.startswith((b"\xfe\xff", b"\xff\xfe")):
        text = value.decode("utf-16", errors="replace")
    else:
        text = value.decode("latin-1", errors="replace")

    return text.strip() or None


def _epub_metadata(path: Path) -> tuple[str | None, str | None]:
    namespace = {"dc": "http://purl.org/dc/elements/1.1/"}

    try:
        with zipfile.ZipFile(path) as archive:
            check_archive(archive)
            opf, _ = read_opf(archive)
    except (OSError, zipfile.BadZipFile, ArchiveTooLargeError, ParsingError, DefusedXmlException):
        # Опись не прочиталась. Текст при этом мог прочитаться: описи
        # бывают с ошибками, и ронять из-за них проверку незачем.
        return None, None

    return _text_of(opf.findtext(".//dc:title", namespaces=namespace)), _text_of(
        opf.findtext(".//dc:creator", namespaces=namespace)
    )


def _docx_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        properties = docx.Document(str(path)).core_properties

        return _text_of(properties.title), _text_of(properties.author)
    except (OSError, zipfile.BadZipFile, ValueError, KeyError):
        return None, None


def _text_of(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _differs(left: str | None, right: str | None) -> bool:
    """Расходятся ли два объявленных названия по сути.

    Сравниваются только заполненные значения: отсутствие сведений — это
    не расхождение, а их отсутствие, и предупреждать о нём не о чем.

    Вхождение одного в другое расхождением не считается: подзаголовок и
    название серии обычны у одного и того же издания.
    """
    if not left or not right:
        return False

    first, second = _normalize(left), _normalize(right)

    if not first or not second:
        return False

    return first not in second and second not in first


def _normalize(value: str) -> str:
    return _SPACES.sub(" ", _NOISE.sub(" ", value.casefold())).strip()
