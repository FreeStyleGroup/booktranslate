"""Разборщики форматов.

Тоже без базы: разборщик принимает файл и отдаёт блоки, и всё, что нужно для
проверки, — временный каталог.
"""

from pathlib import Path

import pytest

from app.models.document import SourceFormat
from app.models.segment import SegmentKind
from app.services.parsers import ParsingError, is_supported, parser_for
from app.services.parsers.markup import EpubParser, HtmlParser
from app.services.parsers.plain import MarkdownParser, PlainTextParser
from tests.factories import epub_bytes, real_docx_bytes


def write(tmp_path: Path, name: str, data: bytes | str) -> Path:
    path = tmp_path / name
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)

    return path


def test_pdf_and_xliff_are_not_parsed_yet() -> None:
    """Неподдержанный формат виден заранее, а не падением при разборе."""
    assert parser_for(SourceFormat.PDF) is None
    assert not is_supported(SourceFormat.XLIFF)
    assert is_supported(SourceFormat.DOCX)


def test_plain_text_splits_on_blank_lines(tmp_path: Path) -> None:
    path = write(tmp_path, "book.txt", "Первый абзац.\n\n\nВторой абзац.\n")
    blocks = list(PlainTextParser().parse(path))

    assert [block.text for block in blocks] == ["Первый абзац.", "Второй абзац."]
    assert all(block.kind is SegmentKind.PARAGRAPH for block in blocks)


def test_windows_encoding_is_read(tmp_path: Path) -> None:
    """Старые выгрузки приходят в CP1251, и падать на них нельзя."""
    path = tmp_path / "legacy.txt"
    path.write_bytes("Русский текст в кодировке Windows".encode("cp1251"))

    blocks = list(PlainTextParser().parse(path))

    assert blocks[0].text == "Русский текст в кодировке Windows"


def test_markdown_recognizes_structure(tmp_path: Path) -> None:
    source = (
        "# Заголовок первого уровня\n"
        "\n"
        "Обычный абзац,\n"
        "разбитый на строки.\n"
        "\n"
        "- первый пункт\n"
        "- второй пункт\n"
        "\n"
        "```python\n"
        "print('это не переводится')\n"
        "```\n"
    )
    blocks = list(MarkdownParser().parse(write(tmp_path, "book.md", source)))
    kinds = [block.kind for block in blocks]

    assert kinds == [
        SegmentKind.HEADING,
        SegmentKind.PARAGRAPH,
        SegmentKind.LIST_ITEM,
        SegmentKind.LIST_ITEM,
        SegmentKind.CODE,
    ]
    assert blocks[0].text == "Заголовок первого уровня"
    assert blocks[0].location["level"] == 1
    assert blocks[1].text == "Обычный абзац,\nразбитый на строки."
    assert "print" in blocks[4].text


def test_markdown_unclosed_code_fence_is_not_lost(tmp_path: Path) -> None:
    blocks = list(MarkdownParser().parse(write(tmp_path, "draft.md", "```\nкод без конца\n")))

    assert [block.kind for block in blocks] == [SegmentKind.CODE]
    assert blocks[0].text == "код без конца"


def test_docx_keeps_order_of_paragraphs_and_tables(tmp_path: Path) -> None:
    path = write(tmp_path, "manual.docx", real_docx_bytes())
    blocks = list(parser_for(SourceFormat.DOCX).parse(path))  # type: ignore[union-attr]

    assert [block.text for block in blocks] == [
        "Глава первая",
        "Первый абзац главы.",
        "Пункт списка",
        "Параметр",
        "Значение",
    ]
    assert blocks[0].kind is SegmentKind.HEADING
    assert blocks[1].kind is SegmentKind.PARAGRAPH
    assert blocks[2].kind is SegmentKind.LIST_ITEM
    assert blocks[3].kind is SegmentKind.TABLE_CELL


def test_broken_docx_raises_parsing_error(tmp_path: Path) -> None:
    path = write(tmp_path, "broken.docx", b"PK\x03\x04 not a document")

    with pytest.raises(ParsingError):
        list(parser_for(SourceFormat.DOCX).parse(path))  # type: ignore[union-attr]


def test_html_does_not_duplicate_nested_blocks(tmp_path: Path) -> None:
    """Текст пункта списка не должен выйти ещё раз внутри абзаца-родителя."""
    source = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<h2>Раздел</h2>"
        "<ul><li>Первый пункт</li><li>Второй пункт</li></ul>"
        "<p>Абзац с <em>выделением</em> внутри.</p>"
        "<script>alert(1)</script>"
        "</body></html>"
    )
    blocks = list(HtmlParser().parse(write(tmp_path, "page.html", source)))

    assert [block.text for block in blocks] == [
        "Раздел",
        "Первый пункт",
        "Второй пункт",
        "Абзац с выделением внутри.",
    ]
    assert [block.kind for block in blocks] == [
        SegmentKind.HEADING,
        SegmentKind.LIST_ITEM,
        SegmentKind.LIST_ITEM,
        SegmentKind.PARAGRAPH,
    ]


def test_epub_follows_spine_not_filenames(tmp_path: Path) -> None:
    """Порядок глав берётся из описи: по алфавиту он был бы обратным."""
    path = write(tmp_path, "book.epub", epub_bytes())
    blocks = list(EpubParser().parse(path))

    assert [block.text for block in blocks] == [
        "Вторая глава",
        "Текст второй главы.",
        "Первая глава",
        "Текст первой главы.",
    ]
    assert blocks[0].location["chapter"] == 0
    assert blocks[2].location["chapter"] == 1


def test_epub_without_container_is_rejected(tmp_path: Path) -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")

    with pytest.raises(ParsingError):
        list(EpubParser().parse(write(tmp_path, "empty.epub", buffer.getvalue())))
