"""DOCX.

Порядок абзацев и таблиц берётся обходом тела документа, а не двумя списками
`document.paragraphs` и `document.tables`: те отдают своё содержимое отдельно,
и таблица, стоящая в середине главы, оказалась бы в конце перевода.

Тип блока определяется по стилю абзаца, а не по внешнему виду: жирный текст
в 16 пунктов заголовком не является, а размеченный стилем «Heading 2» —
является, даже если выглядит как обычный. Стиль задаёт автор осознанно.
"""

from collections.abc import Iterator
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.models.segment import SegmentKind
from app.services.parsers.base import ParsedBlock, ParsingError

# Имена стилей заголовков в русской и английской сборках Word. Сравнение по
# началу строки: у уровней имена «Heading 1», «Заголовок 2» и так далее.
_HEADING_PREFIXES = ("heading", "заголовок", "title", "название")
_CAPTION_PREFIXES = ("caption", "название объекта", "подпись")
_LIST_PREFIXES = ("list paragraph", "абзац списка", "list bullet", "list number", "маркированный")


class DocxParser:
    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        try:
            document = docx.Document(str(path))
        except Exception as error:  # библиотека бросает собственные типы ошибок
            raise ParsingError(f"Файл не читается как DOCX: {error}") from error

        body = document.element.body
        index = 0

        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if text:
                    yield ParsedBlock(
                        text=text,
                        kind=_kind_of(paragraph),
                        location={"block": index, "style": _style_name(paragraph)},
                    )
                    index += 1
                continue

            if child.tag == qn("w:tbl"):
                table = Table(child, document)
                for row_no, row in enumerate(table.rows):
                    for cell_no, cell in enumerate(row.cells):
                        text = cell.text.strip()
                        if not text:
                            continue

                        yield ParsedBlock(
                            text=text,
                            kind=SegmentKind.TABLE_CELL,
                            location={"block": index, "row": row_no, "column": cell_no},
                        )
                index += 1


def _style_name(paragraph: Paragraph) -> str:
    """Имя стиля абзаца.

    Стиля может не быть вовсе: у абзаца, размеченного прямым форматированием,
    ссылка на стиль пустая, и обращение к имени напрямую роняло бы разбор
    всего документа из-за одного такого абзаца.
    """
    style = paragraph.style

    return (style.name or "") if style is not None else ""


def _kind_of(paragraph: Paragraph) -> SegmentKind:
    name = _style_name(paragraph).strip().lower()

    if name.startswith(_HEADING_PREFIXES):
        return SegmentKind.HEADING

    if name.startswith(_CAPTION_PREFIXES):
        return SegmentKind.CAPTION

    if name.startswith(_LIST_PREFIXES) or _is_numbered(paragraph):
        return SegmentKind.LIST_ITEM

    return SegmentKind.PARAGRAPH


def _is_numbered(paragraph: Paragraph) -> bool:
    """Абзац входит в нумерованный или маркированный список.

    Проверяется наличие `w:numPr` в свойствах абзаца — это и есть признак
    списка в разметке. Стиль при этом может называться как угодно: списки
    часто размечают прямым форматированием, минуя стили.
    """
    # Публичного доступа к свойствам абзаца python-docx не даёт.
    properties = paragraph._element.pPr
    return properties is not None and properties.find(qn("w:numPr")) is not None
