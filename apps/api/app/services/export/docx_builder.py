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

import docx

from app.models.segment import SegmentKind
from app.services.export.base import Rendered, TranslatedBlock
from app.services.export.docx_writer import MEDIA_TYPE

# Уровень заголовка известен только там, где его записал разборщик. Для
# остальных — первый: у книги из PDF иерархия заголовков не восстановлена,
# и плоская честнее выдуманной.
DEFAULT_HEADING_LEVEL = 1
MAX_HEADING_LEVEL = 9

MONOSPACE = "Consolas"


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

            if block.kind is SegmentKind.HEADING:
                document.add_heading(text, level=_heading_level(block))
            elif block.kind is SegmentKind.LIST_ITEM:
                document.add_paragraph(text, style="List Bullet")
            elif block.kind is SegmentKind.CODE:
                run = document.add_paragraph().add_run(text)
                run.font.name = MONOSPACE
            elif block.kind is SegmentKind.WARNING:
                document.add_paragraph().add_run(text).bold = True
            elif block.kind is SegmentKind.CAPTION:
                document.add_paragraph().add_run(text).italic = True
            else:
                # Ячейка таблицы — абзацем: сколько в строке колонок, знал
                # только исходник. Потеря вёрстки, но не содержимого.
                document.add_paragraph(text)

        buffer = io.BytesIO()
        document.save(buffer)

        return Rendered(content=buffer.getvalue(), media_type=self.media_type, suffix=self.suffix)


def _heading_level(block: TranslatedBlock) -> int:
    level = block.location.get("level")

    if isinstance(level, int) and 1 <= level <= MAX_HEADING_LEVEL:
        return level

    return DEFAULT_HEADING_LEVEL
