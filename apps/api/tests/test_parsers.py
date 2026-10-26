"""Разборщики форматов.

Тоже без базы: разборщик принимает файл и отдаёт блоки, и всё, что нужно для
проверки, — временный каталог.
"""

from pathlib import Path

import pytest

from app.models.block import BlockKind
from app.models.document import SourceFormat
from app.services.parsers import ParsingError, blocks_of, is_supported, parser_for
from app.services.parsers.docx import DocxParser
from app.services.parsers.markup import EpubParser, HtmlParser
from app.services.parsers.pdf import PdfParser
from app.services.parsers.plain import MarkdownParser, PlainTextParser
from tests.factories import PdfLine, PdfPage, epub_bytes, pdf_bytes, real_docx_bytes


def write(tmp_path: Path, name: str, data: bytes | str) -> Path:
    path = tmp_path / name
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)

    return path


def test_xliff_is_not_parsed_yet() -> None:
    """Неподдержанный формат виден заранее, а не падением при разборе."""
    assert parser_for(SourceFormat.XLIFF) is None
    assert not is_supported(SourceFormat.XLIFF)
    assert is_supported(SourceFormat.PDF)
    assert is_supported(SourceFormat.DOCX)


def _pdf_blocks(tmp_path: Path, pages: list[PdfPage]) -> list:
    return list(blocks_of(PdfParser().parse(write(tmp_path, "manual.pdf", pdf_bytes(pages)))))


def test_pdf_restores_paragraphs_headings_and_lists(tmp_path: Path) -> None:
    """У PDF нет абзацев — есть буквы с координатами; абзацы, заголовок,
    перенос слова и список восстанавливаются по правилам."""
    page = PdfPage(
        lines=(
            PdfLine("1. Installation", size=18),
            PdfLine(""),
            PdfLine("Open the valve before start. Check the"),
            PdfLine("pressure gauge every day."),
            PdfLine(""),
            PdfLine("Warning! Disconnect the power sup-"),
            PdfLine("ply before service."),
            PdfLine(""),
            PdfLine("- Replace the filter"),
            PdfLine("- Close the valve"),
        )
    )

    blocks = _pdf_blocks(tmp_path, [page])

    assert [(block.text, block.kind) for block in blocks] == [
        ("1. Installation", BlockKind.HEADING),
        ("Open the valve before start. Check the pressure gauge every day.", BlockKind.PARAGRAPH),
        ("Warning! Disconnect the power supply before service.", BlockKind.WARNING),
        ("Replace the filter", BlockKind.LIST_ITEM),
        ("Close the valve", BlockKind.LIST_ITEM),
    ]
    # Единственный заголовок — самый крупный, значит первого уровня.
    assert blocks[0].location == {"page": 1, "block": 0, "level": 1}
    # У абзаца уровня нет: уровень — свойство заголовка, а не места.
    assert "level" not in blocks[1].location


def test_pdf_heading_level_is_rank_of_its_size(tmp_path: Path) -> None:
    """Уровень в PDF — ранг кегля среди заголовков книги, а не порог в пунктах."""
    page = PdfPage(
        lines=(
            PdfLine("Chapter 1. Pumps", size=20),
            PdfLine(""),
            PdfLine("Pumps move liquids through the system."),
            PdfLine(""),
            PdfLine("1.1 Centrifugal pumps", size=15),
            PdfLine(""),
            PdfLine("They use a rotating impeller."),
        )
    )

    blocks = _pdf_blocks(tmp_path, [page])
    levels = {block.text: block.location.get("level") for block in blocks}

    assert levels["Chapter 1. Pumps"] == 1
    assert levels["1.1 Centrifugal pumps"] == 2


def test_pdf_drops_running_headers_and_page_numbers(tmp_path: Path) -> None:
    """Колонтитул повторяется на каждой странице и в книгу не входит."""
    # Сам текст на страницах разный: одинаковый с точностью до числа считался
    # бы колонтитулом — и правильно, книга так не пишется.
    chapters = ("Mounting the pump.", "Starting the pump.", "Servicing the pump.")
    pages = [
        PdfPage(
            lines=(
                PdfLine("ACME Pump Manual"),
                PdfLine(""),
                PdfLine(chapter),
                PdfLine(""),
                PdfLine(f"Page {number}"),
            )
        )
        for number, chapter in enumerate(chapters, start=1)
    ]

    blocks = _pdf_blocks(tmp_path, pages)

    assert [block.text for block in blocks] == list(chapters)
    assert [block.location["page"] for block in blocks] == [1, 2, 3]


def test_pdf_glues_a_paragraph_that_came_line_by_line(tmp_path: Path) -> None:
    """В плотной вёрстке pdfminer отдаёт каждую строку своим блоком; абзац
    узнаётся по обрыву строки и склеивается. Телефон крупным кеглем —
    не заголовок."""
    page = PdfPage(
        lines=(
            PdfLine("800 626 2120", size=18, leading=1.9),
            PdfLine("The proper selection of power transmission products,", leading=1.9),
            PdfLine("including the related area of safety, is the", leading=1.9),
            PdfLine("responsibility of the customer.", leading=1.9),
            PdfLine("Operating requirements vary.", leading=1.9),
        )
    )

    blocks = _pdf_blocks(tmp_path, [page])

    assert [(block.text, block.kind) for block in blocks] == [
        ("800 626 2120", BlockKind.PARAGRAPH),
        (
            "The proper selection of power transmission products, including the related "
            "area of safety, is the responsibility of the customer.",
            BlockKind.PARAGRAPH,
        ),
        ("Operating requirements vary.", BlockKind.PARAGRAPH),
    ]


def test_pdf_scan_is_named_a_scan(tmp_path: Path) -> None:
    """Скан — не «текст не нашёлся»: человек пошёл бы чинить исправный файл."""
    with pytest.raises(ParsingError, match="скан"):
        _pdf_blocks(tmp_path, [PdfPage(image=True), PdfPage(image=True)])


def test_pdf_without_text_or_images_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ParsingError, match="не нашлось текста"):
        _pdf_blocks(tmp_path, [PdfPage()])


def test_pdf_garbage_is_reported_not_raised(tmp_path: Path) -> None:
    path = write(tmp_path, "broken.pdf", b"%PDF-1.4\nthis is not a pdf at all")

    with pytest.raises(ParsingError, match="не читается как PDF"):
        list(blocks_of(PdfParser().parse(path)))


def test_plain_text_splits_on_blank_lines(tmp_path: Path) -> None:
    path = write(tmp_path, "book.txt", "Первый абзац.\n\n\nВторой абзац.\n")
    blocks = list(blocks_of(PlainTextParser().parse(path)))

    assert [block.text for block in blocks] == ["Первый абзац.", "Второй абзац."]
    assert all(block.kind is BlockKind.PARAGRAPH for block in blocks)


def test_windows_encoding_is_read(tmp_path: Path) -> None:
    """Старые выгрузки приходят в CP1251, и падать на них нельзя."""
    path = tmp_path / "legacy.txt"
    path.write_bytes("Русский текст в кодировке Windows".encode("cp1251"))

    blocks = list(blocks_of(PlainTextParser().parse(path)))

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
    blocks = list(blocks_of(MarkdownParser().parse(write(tmp_path, "book.md", source))))
    kinds = [block.kind for block in blocks]

    assert kinds == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.LIST_ITEM,
        BlockKind.CODE,
    ]
    assert blocks[0].text == "Заголовок первого уровня"
    assert blocks[0].location["level"] == 1
    assert blocks[1].text == "Обычный абзац,\nразбитый на строки."
    assert "print" in blocks[4].text


def test_markdown_unclosed_code_fence_is_not_lost(tmp_path: Path) -> None:
    blocks = list(
        blocks_of(MarkdownParser().parse(write(tmp_path, "draft.md", "```\nкод без конца\n")))
    )

    assert [block.kind for block in blocks] == [BlockKind.CODE]
    assert blocks[0].text == "код без конца"


def test_docx_keeps_order_of_paragraphs_and_tables(tmp_path: Path) -> None:
    path = write(tmp_path, "manual.docx", real_docx_bytes())
    blocks = list(blocks_of(parser_for(SourceFormat.DOCX).parse(path)))  # type: ignore[union-attr]

    assert [block.text for block in blocks] == [
        "Глава первая",
        "Первый абзац главы.",
        "Пункт списка",
        "Параметр",
        "Значение",
    ]
    assert blocks[0].kind is BlockKind.HEADING
    assert blocks[1].kind is BlockKind.PARAGRAPH
    assert blocks[2].kind is BlockKind.LIST_ITEM
    assert blocks[3].kind is BlockKind.TABLE_CELL


def test_broken_docx_raises_parsing_error(tmp_path: Path) -> None:
    path = write(tmp_path, "broken.docx", b"PK\x03\x04 not a document")

    with pytest.raises(ParsingError):
        list(blocks_of(parser_for(SourceFormat.DOCX).parse(path)))  # type: ignore[union-attr]


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
    blocks = list(blocks_of(HtmlParser().parse(write(tmp_path, "page.html", source))))

    assert [block.text for block in blocks] == [
        "Раздел",
        "Первый пункт",
        "Второй пункт",
        "Абзац с выделением внутри.",
    ]
    assert [block.kind for block in blocks] == [
        BlockKind.HEADING,
        BlockKind.LIST_ITEM,
        BlockKind.LIST_ITEM,
        BlockKind.PARAGRAPH,
    ]


def test_epub_follows_spine_not_filenames(tmp_path: Path) -> None:
    """Порядок глав берётся из описи: по алфавиту он был бы обратным."""
    path = write(tmp_path, "book.epub", epub_bytes())
    blocks = list(blocks_of(EpubParser().parse(path)))

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
        list(blocks_of(EpubParser().parse(write(tmp_path, "empty.epub", buffer.getvalue()))))


def test_html_heading_carries_its_level(tmp_path: Path) -> None:
    """Уровень заголовка — из тега: по нему предлагаются границы глав."""
    source = "<h1>Книга</h1><h2>Глава</h2><h3>Раздел</h3><p>Текст.</p>"
    blocks = list(blocks_of(HtmlParser().parse(write(tmp_path, "page.html", source))))

    assert [block.location.get("level") for block in blocks] == [1, 2, 3, None]


def _docx_with_styles(tmp_path: Path, paragraphs: list[tuple[str, str]]) -> Path:
    """DOCX с абзацами заданных стилей; недостающий стиль заводится.

    Собирается самой python-docx: проверяется разбор, а не умение теста
    воспроизвести формат Word.
    """
    import docx
    from docx.enum.style import WD_STYLE_TYPE

    document = docx.Document()

    for style, text in paragraphs:
        if style not in [item.name for item in document.styles]:
            document.styles.add_style(style, WD_STYLE_TYPE.PARAGRAPH)
        document.add_paragraph(text, style=style)

    path = tmp_path / "styles.docx"
    document.save(str(path))

    return path


def test_docx_heading_level_comes_from_style(tmp_path: Path) -> None:
    path = _docx_with_styles(
        tmp_path,
        [
            ("Title", "Руководство"),
            ("Heading 1", "Глава первая"),
            ("Heading 2", "Раздел"),
            ("Normal", "Абзац."),
        ],
    )
    blocks = list(blocks_of(DocxParser().parse(path)))

    # Заголовок документа — над всеми уровнями: он один и главой не является.
    assert [block.location.get("level") for block in blocks] == [0, 1, 2, None]


def test_russian_caption_style_is_not_a_heading(tmp_path: Path) -> None:
    """«Название объекта» — подпись, хотя и начинается как стиль заголовка."""
    path = _docx_with_styles(tmp_path, [("Название объекта", "Рисунок 1. Насос")])
    blocks = list(blocks_of(DocxParser().parse(path)))

    assert blocks[0].kind is BlockKind.CAPTION
    assert "level" not in blocks[0].location


def test_html_code_listing_keeps_indentation(tmp_path: Path) -> None:
    """Отступ в листинге — содержимое: мастер обязан хранить его знак в знак."""
    source = (
        "<pre>\ndef entropy(p):\n    return -sum(p * log(p))\n\n    # tail\n</pre>"
        "<p>Text  with   spaces.</p>"
    )
    blocks = list(blocks_of(HtmlParser().parse(write(tmp_path, "page.html", source))))

    assert blocks[0].kind is BlockKind.CODE
    # Перевод строки сразу после <pre> по правилам HTML содержимым не
    # является — он и срезан; всё остальное на месте.
    assert blocks[0].text == "def entropy(p):\n    return -sum(p * log(p))\n\n    # tail"
    # Вне листинга пробелы HTML — оформление файла: читатель книги видит
    # один пробел, и в мастере он один.
    assert blocks[1].text == "Text with spaces."


def test_html_text_is_what_the_reader_sees(tmp_path: Path) -> None:
    """Узлы соединяются без выдуманных пробелов; `<br>` — перевод строки; NBSP — собой."""
    source = (
        '<p>Listed in <a href="#t1">Table 1.1</a>.</p>'
        "<p>Line one<br/>\n  line <b>two</b>,\n  done.</p>"
        "<p>10 bar</p>"
    )
    blocks = list(blocks_of(HtmlParser().parse(write(tmp_path, "page.html", source))))

    assert [block.text for block in blocks] == [
        "Listed in Table 1.1.",
        "Line one\nline two, done.",
        "10 bar",
    ]


def test_markdown_code_keeps_first_line_indent(tmp_path: Path) -> None:
    source = "Text.\n\n```\n    indented()\n  less()\n```\n"
    blocks = list(blocks_of(MarkdownParser().parse(write(tmp_path, "book.md", source))))

    assert blocks[1].kind is BlockKind.CODE
    assert blocks[1].text == "    indented()\n  less()"
