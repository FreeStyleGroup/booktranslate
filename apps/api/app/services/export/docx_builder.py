"""Сборка DOCX с нуля — для исходников, которые обратно в себя не собираются.

PDF в PDF не вписать: перевод длиннее оригинала, а PDF — это координаты
букв, и подвинуть их значит переверстать книгу. Поэтому из PDF, EPUB и
разметки перевод отдаётся новым документом Word: заголовки, абзацы, списки,
подписи и предупреждения в нём размечены стилями, и заказчик получает файл,
который правится где угодно.

Это не восстановление оригинала, и подавать его так нельзя: оформление,
картинки и таблицы исходника сюда не переносятся. Документ Word из DOCX
собирается иначе — по месту, в `docx_writer.py`, — и там всё это остаётся.
"""

import io
from pathlib import Path
from typing import Any

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches
from PIL import Image, UnidentifiedImageError

from app.models.block import BlockKind
from app.services.export.base import Rendered, TranslatedBlock
from app.services.export.document import (
    FigureElement,
    PublicationDocument,
    TableCell,
    TableElement,
    TextElement,
)
from app.services.export.docx_writer import MEDIA_TYPE

# Уровень заголовка известен только там, где его записал разборщик. Для
# остальных — первый: у книги из PDF иерархия заголовков не восстановлена,
# и плоская честнее выдуманной.
DEFAULT_HEADING_LEVEL = 1
MAX_HEADING_LEVEL = 9

MONOSPACE = "Consolas"

# Какие форматы Word вставляет как есть. Остальное переводится в PNG.
WORD_IMAGES = frozenset({"image/png", "image/jpeg", "image/gif"})
PAGE_TEXT_WIDTH_INCHES = 6.0


class DocxBuilder:
    media_type = MEDIA_TYPE
    suffix = ".docx"

    @property
    def needs_source(self) -> bool:
        return False

    def render(self, blocks: list[TranslatedBlock], *, source: Path | None = None) -> Rendered:
        document = docx.Document()

        for block in blocks:
            text = block.text.strip()
            if not text:
                continue

            if block.kind is BlockKind.HEADING:
                document.add_heading(text, level=_heading_level(block))
            elif block.kind is BlockKind.LIST_ITEM:
                document.add_paragraph(text, style="List Bullet")
            elif block.kind is BlockKind.CODE:
                run = document.add_paragraph().add_run(text)
                run.font.name = MONOSPACE
            elif block.kind is BlockKind.WARNING:
                document.add_paragraph().add_run(text).bold = True
            elif block.kind is BlockKind.CAPTION:
                document.add_paragraph().add_run(text).italic = True
            else:
                # Ячейка таблицы — абзацем: сколько в строке колонок, знал
                # только исходник. Потеря вёрстки, но не содержимого.
                document.add_paragraph(text)

        buffer = io.BytesIO()
        document.save(buffer)

        return Rendered(content=buffer.getvalue(), media_type=self.media_type, suffix=self.suffix)

    def render_document(self, source: PublicationDocument) -> Rendered:
        """Новый документ из содержания выпуска: с настоящими таблицами и рисунками."""
        document = docx.Document()

        for element in source.elements:
            if isinstance(element, TextElement):
                _add_text(document, element.kind, element.text, element.level)
            elif isinstance(element, TableElement):
                _add_table(document, element)
            elif isinstance(element, FigureElement):
                _add_figure(document, element, source)
            else:
                paragraph = document.add_paragraph()
                paragraph.add_run(element.text).italic = True
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        buffer = io.BytesIO()
        document.save(buffer)

        return Rendered(content=buffer.getvalue(), media_type=self.media_type, suffix=self.suffix)


def _heading_level(block: TranslatedBlock) -> int:
    level = block.location.get("level")

    if isinstance(level, int) and 1 <= level <= MAX_HEADING_LEVEL:
        return level

    return DEFAULT_HEADING_LEVEL


def _add_text(document: Any, kind: BlockKind, text: str, level: int = 1) -> None:
    clean = text.strip()
    if not clean:
        return

    if kind is BlockKind.HEADING:
        document.add_heading(clean, level=min(max(level, 1), MAX_HEADING_LEVEL))
    elif kind is BlockKind.LIST_ITEM:
        document.add_paragraph(clean, style="List Bullet")
    elif kind is BlockKind.CODE:
        document.add_paragraph().add_run(clean).font.name = MONOSPACE
    elif kind is BlockKind.WARNING:
        document.add_paragraph().add_run(clean).bold = True
    elif kind is BlockKind.CAPTION:
        document.add_paragraph().add_run(clean).italic = True
    else:
        document.add_paragraph(clean)


def _add_table(document: Any, element: TableElement) -> None:
    """Таблица с объединёнными ячейками. Занятые места считаются по строкам сверху вниз."""
    placed: list[tuple[int, int, TableCell]] = []
    taken: set[tuple[int, int]] = set()
    width = 0

    for row_no, row in enumerate(element.rows):
        column = 0
        for cell in row:
            while (row_no, column) in taken:
                column += 1
            placed.append((row_no, column, cell))
            for down in range(cell.rowspan):
                for right in range(cell.colspan):
                    taken.add((row_no + down, column + right))
            column += cell.colspan
        width = max(width, column)

    height = max((row for row, _ in taken), default=-1) + 1
    if height == 0 or width == 0:
        return

    width = max(width, max(column for _, column in taken) + 1)
    table = document.add_table(rows=height, cols=width)
    table.style = "Table Grid"

    for row_no, column, cell in placed:
        target = table.cell(row_no, column)
        if cell.rowspan > 1 or cell.colspan > 1:
            target = target.merge(table.cell(row_no + cell.rowspan - 1, column + cell.colspan - 1))
        run = target.paragraphs[0].add_run(cell.text)
        run.bold = cell.header


def _add_figure(document: Any, element: FigureElement, source: PublicationDocument) -> None:
    for url, alt in zip(element.urls, element.alts, strict=True):
        found = source.images.get(url)
        if found is None:
            continue

        content, media_type = found

        picture = content if media_type in WORD_IMAGES else _as_png(content)
        if picture is None:
            # Вектор Word так не примет: честная подпись лучше пропавшего рисунка.
            document.add_paragraph().add_run(f"[Рисунок: {alt or 'см. PDF'}]").italic = True
            continue

        document.add_picture(io.BytesIO(picture), width=Inches(_width_inches(picture)))


def _as_png(content: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(content)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None

    return buffer.getvalue()


def _width_inches(content: bytes) -> float:
    """Ширина на странице: как есть при 96 точках на дюйм, но не шире текста."""
    with Image.open(io.BytesIO(content)) as image:
        return float(min(image.size[0] / 96, PAGE_TEXT_WIDTH_INCHES))
