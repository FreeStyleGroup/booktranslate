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
фрагмент, из остальных текст убирается. Иначе никак — в сегменте лежит
текст, и полужирного слова посреди фразы в нём нет с самого разбора. Но из
фрагментов уходит только то, что разбор читал как текст: картинка, сноска,
разрыв страницы, символ в текст сегмента не попадали и остаются на своих
местах. Оформление самого абзаца (стиль, отступы, нумерация) остаётся: оно
живёт не в фрагментах.
"""

import io
from pathlib import Path
from typing import Any, cast

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.text.run import CT_R
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.export.base import ExportError, Rendered, TranslatedBlock

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Руны, текст которых читал разбор. `paragraph.text` в python-docx
# складывает прямые `w:r` и `w:r` внутри `w:hyperlink` — и ничего больше.
# Руны в `w:ins`, `w:sdt`, `w:smartTag` разбор не видел, их текста в сегменте
# нет, и трогать их — портить то, что в перевод не попадало.
_READ_RUNS = "./w:r | ./w:hyperlink/w:r"

# Узлы руны, которые разбор превратил в текст сегмента (`run.text`): буквы,
# табуляция, мягкий перенос. Перевод замещает их целиком — вместе с `\n` и
# `\t`, которыми они были в сегменте. Разрыв страницы (`w:br` с type="page"),
# картинка, сноска, символ в текст не попадали, и их сборка не трогает.
_TEXT_TAGS = frozenset(
    qn(tag) for tag in ("w:t", "w:delText", "w:tab", "w:cr", "w:noBreakHyphen", "w:ptab")
)


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

    Текст уходит в первую руну со словами — она несёт начертание, которым
    набран абзац; из остальных текст убирается, а сами руны остаются: в них
    могут лежать картинка или сноска, и место у них своё.
    """
    runs = _text_runs(paragraph._p)

    if not runs:
        paragraph.add_run(text)
        return

    _write(runs[0], text)

    for run in runs[1:]:
        _clear(run)


def _replace_cell(cell: Any, text: str) -> None:
    """Заменить текст ячейки.

    Ячейка — это набор абзацев. Перевод кладётся в первый, из остальных
    текст убирается: разбор читал ячейку одной строкой, и разложить перевод
    обратно по абзацам не по чему.
    """
    paragraphs = cell.paragraphs

    if not paragraphs:
        cell.text = text
        return

    _replace(paragraphs[0], text)

    for paragraph in paragraphs[1:]:
        for run in _text_runs(paragraph._p):
            _clear(run)


def _text_runs(paragraph: CT_P) -> list[CT_R]:
    """Руны абзаца с текстом — в порядке документа, руна со словами первой.

    Разбор читал руны и внутри гиперссылок, поэтому `paragraph.runs` здесь
    не годится: он отдаёт только прямые, и текст ссылки остался бы в файле
    рядом с переводом. Руна из одних пробелов на первое место не претендует:
    перевод должен унаследовать начертание слов, а не отбивки перед ними.
    """
    runs: list[CT_R] = paragraph.xpath(_READ_RUNS)
    with_text = [run for run in runs if _text_nodes(run)]

    with_text.sort(key=lambda run: not _has_words(run))

    return with_text


def _text_nodes(run: CT_R) -> list[Any]:
    return [node for node in run if _is_text(node)]


def _is_text(node: Any) -> bool:
    # Разрыв страницы или колонки — тот же `w:br`, но в тексте сегмента
    # он ничем не отражался, значит, и текстом не считается.
    if node.tag == qn("w:br"):
        return bool(node.get(qn("w:type"), "textWrapping") == "textWrapping")

    return bool(node.tag in _TEXT_TAGS)


def _has_words(run: CT_R) -> bool:
    return any(
        (node.text or "").strip() for node in run if node.tag in (qn("w:t"), qn("w:delText"))
    )


def _write(run: CT_R, text: str) -> None:
    """Вписать текст на место первого текстового узла руны.

    Именно на место, а не в конец: картинка или сноска, стоявшие после
    текста, должны и после перевода стоять после него.
    """
    nodes = _text_nodes(run)
    position = run.index(nodes[0])

    _clear(run)

    for offset, node in enumerate(_content(text)):
        run.insert(position + offset, node)


def _clear(run: CT_R) -> None:
    for node in _text_nodes(run):
        run.remove(node)


def _content(text: str) -> list[Any]:
    """Узлы руны для текста: `w:t`, а `\\t` и `\\n` — как `w:tab` и `w:br`.

    Раскладывает сама библиотека, через запись во временную руну: правила
    (`xml:space="preserve"` у текста с пробелами по краям, перенос как
    разрыв строки) её, и дублировать их здесь — разойтись с ней при первом
    обновлении.
    """
    scratch = cast(CT_R, OxmlElement("w:r"))
    scratch.text = text

    return list(scratch)


def _save(document: Any) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()
