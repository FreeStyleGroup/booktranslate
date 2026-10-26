"""Предложение глав: разделы и группировка, без базы.

Разбор — настоящий: EPUB, HTML и Markdown проходят через свои
разборщики, а не подменяются списком блоков. Так проверяется то, что
действительно увидит человек на экране «Структура книги».
"""

from pathlib import Path

from app.models.block import BlockKind
from app.models.chapter import Chapter, ChapterOrigin
from app.services.chapter_detection import chapter_level, propose, sections_of
from app.services.parsers.base import ParsedBlock
from app.services.parsers.markup import EpubParser, HtmlParser
from app.services.parsers.plain import MarkdownParser, PlainTextParser
from tests.factories import epub_bytes


def _parse_html(tmp_path: Path, markup: str) -> list[ParsedBlock]:
    path = tmp_path / "book.html"
    path.write_text(markup, encoding="utf-8")

    return list(HtmlParser().parse(path))


BOOK = (
    "<h1>Machine Learning for Asset Managers</h1>"
    "<p>Preface text.</p>"
    "<h2>1. Introduction</h2><p>Why ML.</p>"
    "<h3>1.1 Motivation</h3><p>Because.</p><ul><li>One</li><li>Two</li></ul>"
    "<h2>2. Denoising</h2><p>Noise.</p>"
    "<h2>3. Distance Metrics</h2><p>Metrics.</p>"
)


def test_chapters_start_at_the_repeated_top_level(tmp_path: Path) -> None:
    """Одиночный `h1` — название книги, главы — повторяющиеся `h2`."""
    proposals = propose(sections_of(_parse_html(tmp_path, BOOK)))

    assert [proposal.title for proposal in proposals] == [
        # То, что до первой главы, — отдельная вступительная часть: её
        # объединят или оставят, но молча приклеить к первой главе нельзя.
        "Machine Learning for Asset Managers",
        "1. Introduction",
        "2. Denoising",
        "3. Distance Metrics",
    ]
    assert all(proposal.origin is ChapterOrigin.HEADING for proposal in proposals)


def test_subsections_stay_inside_their_chapter(tmp_path: Path) -> None:
    proposals = propose(sections_of(_parse_html(tmp_path, BOOK)))
    introduction = proposals[1]

    assert [section.title for section in introduction.sections] == [
        "1. Introduction",
        "1.1 Motivation",
    ]
    assert [section.level for section in introduction.sections] == [2, 3]


def test_chapters_cover_the_book_without_gaps(tmp_path: Path) -> None:
    """Границы стыкуются: конец главы — начало следующей, ни блока мимо."""
    blocks = _parse_html(tmp_path, BOOK)
    proposals = propose(sections_of(blocks))

    assert proposals[0].start == 0
    assert proposals[-1].end == len(blocks)
    assert all(
        left.end == right.start for left, right in zip(proposals, proposals[1:], strict=False)
    )


def test_inventory_counts_blocks_by_kind(tmp_path: Path) -> None:
    proposals = propose(sections_of(_parse_html(tmp_path, BOOK)))
    chapter = Chapter(sections=[section.as_json() for section in proposals[1].sections])

    assert chapter.inventory == {"heading": 2, "paragraph": 2, "list_item": 2}


def test_epub_chapter_knows_its_file(tmp_path: Path) -> None:
    """Глава EPUB показывает файл, с которого начинается, — по описи, не по имени."""
    path = tmp_path / "book.epub"
    path.write_bytes(epub_bytes())

    proposals = propose(sections_of(list(EpubParser().parse(path))))

    assert [proposal.title for proposal in proposals] == ["Вторая глава", "Первая глава"]
    assert proposals[0].locator["href"].endswith("part0010.xhtml")


def test_epub_without_headings_is_split_by_files(tmp_path: Path) -> None:
    """Нет заголовков — главой становится файл EPUB, как его разрезал издатель."""
    path = tmp_path / "book.epub"
    path.write_bytes(
        epub_bytes(
            [
                ("one.xhtml", "<p>Первая часть текста.</p><p>Ещё абзац.</p>"),
                ("two.xhtml", "<p>Вторая часть текста.</p>"),
            ]
        )
    )

    proposals = propose(sections_of(list(EpubParser().parse(path))))

    assert len(proposals) == 2
    assert all(proposal.origin is ChapterOrigin.PATH for proposal in proposals)
    # Названия нет — и оно не выдумывается: его даст человек.
    assert all(proposal.title is None for proposal in proposals)


def test_pdf_pages_without_headings_become_sections_of_one_chapter() -> None:
    """Страница PDF — не глава, а место, по которому человек главу разделит."""
    blocks = [
        ParsedBlock(text="Текст первой страницы.", location={"page": 1, "block": 0}),
        ParsedBlock(text="Продолжение.", location={"page": 1, "block": 1}),
        ParsedBlock(text="Текст второй страницы.", location={"page": 2, "block": 2}),
    ]

    proposals = propose(sections_of(blocks))

    assert len(proposals) == 1
    assert proposals[0].origin is ChapterOrigin.PAGE
    assert [section.locator for section in proposals[0].sections] == [{"page": 1}, {"page": 2}]


def test_plain_text_is_one_chapter(tmp_path: Path) -> None:
    path = tmp_path / "book.txt"
    path.write_text("Первый абзац.\n\nВторой абзац.", encoding="utf-8")

    proposals = propose(sections_of(list(PlainTextParser().parse(path))))

    assert len(proposals) == 1
    assert proposals[0].origin is ChapterOrigin.WHOLE


def test_markdown_chapter_points_to_its_line(tmp_path: Path) -> None:
    path = tmp_path / "book.md"
    path.write_text("# Глава 1\n\nТекст.\n\n# Глава 2\n\nТекст.\n", encoding="utf-8")

    proposals = propose(sections_of(list(MarkdownParser().parse(path))))

    assert [proposal.title for proposal in proposals] == ["Глава 1", "Глава 2"]
    assert proposals[1].locator == {"line": 5}


def test_heading_text_is_one_line() -> None:
    """Перенос строки внутри заголовка в названии главы не нужен."""
    blocks = [
        ParsedBlock(text="Chapter 1.\nPumps", kind=BlockKind.HEADING, location={"level": 1}),
        ParsedBlock(text="Text.", location={}),
    ]

    assert propose(sections_of(blocks))[0].title == "Chapter 1. Pumps"


def test_chapter_level_skips_a_single_top_heading() -> None:
    assert chapter_level([1, 2, 2, 3]) == 2
    # Повторов нет — глава одна, и начинает её самый верхний заголовок.
    assert chapter_level([2, 3]) == 2
    assert chapter_level([1, 1, 2]) == 1


def test_empty_source_gives_no_chapters() -> None:
    assert propose(sections_of([])) == []
