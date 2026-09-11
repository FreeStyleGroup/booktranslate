"""Сборка DOCX: перевод встаёт туда, откуда разбор взял текст, и только туда.

Без базы: документ собирается python-docx в памяти, разбирается тем же
разборщиком, что и в бою, и переписывается сборщиком. Проверяется не
«похожий» обход, а тот самый: гиперссылки, картинки, сноски и разрывы —
всё, чего в тексте сегмента нет, — обязаны остаться в файле заказчика.
"""

import io
from pathlib import Path
from typing import Any

import docx
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.export.base import TranslatedBlock
from app.services.export.docx_writer import DocxRenderer
from app.services.parsers.docx import DocxParser


def roundtrip(document: Any, tmp_path: Path, translate: dict[str, str]) -> Any:
    """Разобрать документ, перевести по словарю «исходник → перевод», собрать.

    Блок, которого в словаре нет, уходит исходным текстом: так сразу видно,
    если разбор прочитал не то, что ожидал тест, — KeyError укажет на текст.
    """
    source = tmp_path / "source.docx"
    document.save(source)

    blocks = [
        TranslatedBlock(text=translate[block.text], kind=block.kind, location=block.location)
        for block in DocxParser().parse(source)
    ]
    rendered = DocxRenderer().render(blocks, source=source)

    return docx.Document(io.BytesIO(rendered.content))


def add_hyperlink(paragraph: Any, text: str) -> None:
    """Внутренняя ссылка (`w:anchor`): ей не нужна запись в отношениях части."""
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), "top")

    run = OxmlElement("w:r")
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    hyperlink.append(run)

    paragraph._p.append(hyperlink)


def inner_tags(element: Any) -> list[str]:
    """Содержимое рун в порядке документа, без свойств `w:rPr`."""
    return [node.tag.split("}")[1] for node in element.xpath(".//w:r/*[not(self::w:rPr)]")]


def test_hyperlink_text_is_replaced_not_doubled(tmp_path: Path) -> None:
    """Разбор читал ссылку как часть абзаца — сборка обязана её и переписать."""
    document = docx.Document()
    paragraph = document.add_paragraph("See ")
    add_hyperlink(paragraph, "the manual")
    paragraph.add_run(" before start.")

    result = roundtrip(
        document, tmp_path, {"See the manual before start.": "Смотрите руководство до запуска."}
    )

    assert result.paragraphs[0].text == "Смотрите руководство до запуска."
    # Сама ссылка осталась: адрес — не текст, и терять его незачем.
    assert len(result.paragraphs[0].hyperlinks) == 1


def test_paragraph_made_only_of_hyperlink_is_replaced(tmp_path: Path) -> None:
    """Прямых рун у такого абзаца нет, но текст у него есть — его и переводим."""
    document = docx.Document()
    add_hyperlink(document.add_paragraph(), "Read the manual")

    result = roundtrip(document, tmp_path, {"Read the manual": "Читайте руководство"})

    assert result.paragraphs[0].text == "Читайте руководство"


def test_drawing_and_footnote_stay_in_place(tmp_path: Path) -> None:
    """Картинка и сноска — не текст: их разбор не видел, значит, и сборка не трогает."""
    document = docx.Document()
    paragraph = document.add_paragraph()

    first = paragraph.add_run("Figure 1")
    first._r.append(OxmlElement("w:drawing"))

    second = paragraph.add_run(" shows the valve")
    reference = OxmlElement("w:footnoteReference")
    reference.set(qn("w:id"), "1")
    second._r.append(reference)

    result = roundtrip(
        document, tmp_path, {"Figure 1 shows the valve": "На рисунке 1 показан клапан"}
    )

    assert result.paragraphs[0].text == "На рисунке 1 показан клапан"
    # Перевод — в первой руне, картинка и сноска остались на своих местах
    # относительно него.
    assert inner_tags(result.paragraphs[0]._p) == ["t", "drawing", "footnoteReference"]


def test_page_break_survives_translation(tmp_path: Path) -> None:
    """Разрыв страницы в тексте сегмента не отражался — значит, он не текст."""
    document = docx.Document()
    run = document.add_paragraph().add_run("End of chapter")
    run.add_break(WD_BREAK.PAGE)

    result = roundtrip(document, tmp_path, {"End of chapter": "Конец главы"})

    assert result.paragraphs[0].text == "Конец главы"
    assert len(result.paragraphs[0]._p.xpath('.//w:br[@w:type="page"]')) == 1


def test_table_cell_keeps_its_line_break(tmp_path: Path) -> None:
    """Перенос строки в ячейке разбор читал как `\\n` — в переводе он и возвращается."""
    document = docx.Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].add_run().text = "Line one\nLine two"

    result = roundtrip(document, tmp_path, {"Line one\nLine two": "Строка раз\nСтрока два"})

    translated = result.tables[0].cell(0, 0)

    assert translated.text == "Строка раз\nСтрока два"
    assert len(translated._tc.xpath(".//w:br")) == 1


def test_second_cell_paragraph_keeps_its_drawing(tmp_path: Path) -> None:
    """Очистка остальных абзацев ячейки тоже не должна уносить картинки."""
    document = docx.Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].add_run("Caption")
    run = cell.add_paragraph().add_run("Picture")
    run._r.append(OxmlElement("w:drawing"))

    result = roundtrip(document, tmp_path, {"Caption\nPicture": "Подпись\nКартинка"})

    translated = result.tables[0].cell(0, 0)

    assert translated.text.strip() == "Подпись\nКартинка"
    assert len(translated._tc.xpath(".//w:drawing")) == 1
