"""Выбор разборщика по формату документа.

Реестр, а не цепочка `if`: формат уже определён при приёме файла и хранится
в записи, поэтому здесь остаётся только сопоставление. Отсутствие формата в
реестре — не ошибка кода, а честное «этот формат пока не разбираем».
"""

from app.models.document import SourceFormat
from app.services.parsers.base import DocumentParser, ParsedBlock, ParsingError
from app.services.parsers.docx import DocxParser
from app.services.parsers.markup import EpubParser, HtmlParser
from app.services.parsers.plain import MarkdownParser, PlainTextParser

_PARSERS: dict[SourceFormat, type[DocumentParser]] = {
    SourceFormat.TXT: PlainTextParser,
    SourceFormat.MARKDOWN: MarkdownParser,
    SourceFormat.DOCX: DocxParser,
    SourceFormat.HTML: HtmlParser,
    SourceFormat.EPUB: EpubParser,
    # PDF и XLIFF пока не разбираются.
    #
    # PDF — не разметка, а описание того, где какая буква нарисована: абзацы,
    # колонки и переносы в нём приходится восстанавливать, и от качества
    # этого восстановления зависит весь перевод. Это отдельная задача с
    # выбором библиотеки извлечения и проверкой на настоящих книгах, а не
    # строчка в реестре.
    #
    # XLIFF — уже разобранный кем-то набор сегментов; его разбор означает
    # уважение к чужой разбивке и перенос статусов, а не нарезку заново.
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
