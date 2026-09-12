"""Выбор разборщика по формату документа.

Реестр, а не цепочка `if`: формат уже определён при приёме файла и хранится
в записи, поэтому здесь остаётся только сопоставление. Отсутствие формата в
реестре — не ошибка кода, а честное «этот формат пока не разбираем».
"""

from app.models.document import SourceFormat
from app.services.parsers.base import DocumentParser, ParsedBlock, ParsingError
from app.services.parsers.docx import DocxParser
from app.services.parsers.markup import EpubParser, HtmlParser
from app.services.parsers.pdf import PdfParser
from app.services.parsers.plain import MarkdownParser, PlainTextParser

_PARSERS: dict[SourceFormat, type[DocumentParser]] = {
    SourceFormat.TXT: PlainTextParser,
    SourceFormat.MARKDOWN: MarkdownParser,
    SourceFormat.DOCX: DocxParser,
    SourceFormat.HTML: HtmlParser,
    SourceFormat.EPUB: EpubParser,
    # Только с текстовым слоем: скан честно отвечает, что он скан.
    SourceFormat.PDF: PdfParser,
    # XLIFF пока не разбирается: это уже разобранный кем-то набор
    # сегментов, и его разбор означает уважение к чужой разбивке и перенос
    # статусов, а не нарезку заново.
}


def parser_for(source_format: SourceFormat) -> DocumentParser | None:
    """Разборщик для формата или None, если формат ещё не поддержан."""
    parser_type = _PARSERS.get(source_format)

    return parser_type() if parser_type is not None else None


def is_supported(source_format: SourceFormat) -> bool:
    return source_format in _PARSERS


__all__ = [
    "DocumentParser",
    "ParsedBlock",
    "ParsingError",
    "is_supported",
    "parser_for",
]
