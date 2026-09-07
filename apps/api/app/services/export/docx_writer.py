"""Сборка DOCX: перевод вписывается в исходный файл по месту.

Собирать документ Word с нуля из блоков нельзя. В файле помимо текста есть
стили, нумерация, колонтитулы, поля, сноски, картинки и таблицы с их
разметкой — всего этого разбор не видел, и новый документ вышел бы голым
текстом с потерей всего оформления заказчика.

Поэтому берётся оригинал и в нём заменяется текст. Обход тела повторяет
обход разборщика ровно — по нему и восстанавливается соответствие: у блока
записан его номер в этом обходе, и разойтись они не могут, пока обход один
и тот же. Именно поэтому он здесь продублирован, а не «примерно такой же».

Внутреннее оформление абзаца при замене теряется: перевод кладётся в первый
фрагмент, остальные очищаются. Иначе никак — в сегменте лежит текст, и
полужирного слова посреди фразы в нём нет с самого разбора. Оформление
самого абзаца (стиль, отступы, нумерация) остаётся: оно живёт не в
фрагментах.
"""

import io
from pathlib import Path
from typing import Any

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.export.base import ExportError, Rendered, TranslatedBlock

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocxRenderer:
    media_type = MEDIA_TYPE
    suffix = ".docx"

    @property
    def needs_source(self) -> bool:
        return True

    def render(self, blocks: list[TranslatedBlock], *, source: Path | None) -> Rendered:
        if source is None:
            raise ExportError("Для сборки DOCX нужен исходный файл")

        try:
            document = docx.Document(str(source))
        except Exception as error:  # библиотека бросает собственные типы ошибок
            raise ExportError(f"Исходный файл не читается как DOCX: {error}") from error

        translations = _by_place(blocks)

        body = document.element.body
        index = 0

        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph = Paragraph(child, document)
                if not paragraph.text.strip():
                    continue

                text = translations.get((index, None, None))
                if text is not None:
                    _replace(paragraph, text)

                index += 1
                continue

            if child.tag == qn("w:tbl"):
                table = Table(child, document)
                for row_no, row in enumerate(table.rows):
                    for cell_no, cell in enumerate(row.cells):
                        if not cell.text.strip():
                            continue

                        text = translations.get((index, row_no, cell_no))
                        if text is None:
                            continue

                        _replace_cell(cell, text)

                index += 1

        buffer = _save(document)

        return Rendered(content=buffer, media_type=self.media_type, suffix=self.suffix)


def _by_place(blocks: list[TranslatedBlock]) -> dict[tuple[int, int | None, int | None], str]:
    """Переводы по месту в обходе: номер блока, строка и колонка таблицы."""
    result: dict[tuple[int, int | None, int | None], str] = {}

    for block in blocks:
        place = block.location
        number = place.get("block")

        # Блок без номера пришёл не из разбора DOCX — вписывать его некуда.
        if not isinstance(number, int):
            continue

        result[(number, _int_or_none(place.get("row")), _int_or_none(place.get("column")))] = (
            block.text
        )

    return result


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _replace(paragraph: Paragraph, text: str) -> None:
    """Заменить текст абзаца, сохранив его оформление.

    Текст уходит в первый фрагмент — он несёт начертание, которым набран
    абзац; остальные очищаются, а не удаляются: удаление узлов на ходу
    ломает обход, а пустой фрагмент в файле безвреден.
    """
    runs = paragraph.runs

    if not runs:
        paragraph.add_run(text)
        return

    runs[0].text = text

    for run in runs[1:]:
        run.text = ""


def _replace_cell(cell: Any, text: str) -> None:
    """Заменить текст ячейки.

    Ячейка — это набор абзацев. Перевод кладётся в первый, остальные
    очищаются: разбор читал ячейку одной строкой, и разложить перевод
    обратно по абзацам не по чему.
    """
    paragraphs = cell.paragraphs

    if not paragraphs:
        cell.text = text
        return

    _replace(paragraphs[0], text)

    for paragraph in paragraphs[1:]:
        for run in paragraph.runs:
            run.text = ""


def _save(document: Any) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()
