"""Настоящая сборка PDF. Нужны системные библиотеки Pango: они есть в образе и в CI.

На машине без них тест пропускается, но в CI пропуск запрещён переменной `REQUIRE_PDF_ENGINE`: иначе
зелёный прогон не значил бы, что PDF вообще собирается.
"""

import io
import os

import pytest

from app.models.block import BlockKind
from app.services.export.base import ExportError
from app.services.export.document import (
    FigureElement,
    PublicationDocument,
    TableCell,
    TableElement,
    TextElement,
    TocEntry,
)
from app.services.export.pdf import (
    _render_with_weasyprint,
    page_count,
    page_png,
    render_isolated,
    text_layer,
)
from app.services.export.scan import scan


def _engine_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False

    return True


if not _engine_available():
    if os.environ.get("REQUIRE_PDF_ENGINE"):
        raise RuntimeError("Движок PDF недоступен, а здесь он обязателен")

    pytestmark = pytest.mark.skip(reason="нет системных библиотек Pango")


def picture() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buffer, format="PNG")

    return buffer.getvalue()


def book() -> PublicationDocument:
    return PublicationDocument(
        title="Насосы и клапаны",
        language="ru",
        elements=[
            TextElement("h1", BlockKind.HEADING, "Глава первая. Насосы", 1),
            TextElement("p1", BlockKind.PARAGRAPH, "Предохранительный клапан защищает насос."),
            TableElement(
                rows=[
                    [TableCell("Давление", header=True, block_id="c1"), TableCell("12,5 бар")],
                    [TableCell("Объединённая", colspan=2, block_id="c2")],
                ]
            ),
            FigureElement(urls=["asset:0"], alts=["Схема"]),
            TextElement("cap", BlockKind.CAPTION, "Рисунок 1 — схема насоса"),
            TextElement("code", BlockKind.CODE, "open(relief)\n    wait(5)"),
            TextElement("h2", BlockKind.HEADING, "Глава вторая. Обслуживание", 1),
            TextElement("p2", BlockKind.PARAGRAPH, "Проверяйте клапан ежедневно. " * 400),
        ],
        toc=[
            TocEntry(1, "Глава первая. Насосы", "h1"),
            TocEntry(1, "Глава вторая. Обслуживание", "h2"),
        ],
        images={"asset:0": (picture(), "image/png")},
    )


def test_book_is_rendered_with_russian_text_and_pages() -> None:
    rendered = _render_with_weasyprint(book())

    assert rendered.content.startswith(b"%PDF")
    assert rendered.renderer.startswith("weasyprint-")
    assert page_count(rendered.content) == len(rendered.page_map) >= 3
    assert page_png(rendered.content, 1).startswith(b"\x89PNG")

    text = text_layer(rendered.content)
    assert "Предохранительный клапан" in text
    assert "12,5 бар" in text
    # Оглавление с номерами страниц и нумерация служебного не приносят.
    assert "Оглавление" in text
    assert scan(text) == []


def test_planted_service_code_is_found_in_the_text_layer() -> None:
    """Иначе чистый результат проверки выше ничего бы не значил."""
    rendered = _render_with_weasyprint(
        PublicationDocument(
            title="Т",
            language="ru",
            elements=[TextElement("p", BlockKind.PARAGRAPH, "Смотрите CH03-B0042 ниже.")],
        )
    )

    assert scan(text_layer(rendered.content))


def test_page_map_knows_where_blocks_stand() -> None:
    rendered = _render_with_weasyprint(book())
    placed = {block for page in rendered.page_map for block in page}

    assert {"h1", "p1", "c1", "c2", "cap", "code", "h2", "p2"} <= placed
    first = next(i for i, page in enumerate(rendered.page_map) if "h1" in page)
    second = next(i for i, page in enumerate(rendered.page_map) if "h2" in page)
    assert second > first


def test_outside_resources_are_refused() -> None:
    document = book()
    document.elements.append(FigureElement(urls=["file:///etc/passwd"], alts=["x"]))

    # Ошибка у движка фатальная и нарочно не наследует Exception: её ничто не проглотит по дороге.
    with pytest.raises(BaseException, match="за пределы выпуска"):
        _render_with_weasyprint(document)


async def test_render_runs_in_a_separate_process() -> None:
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1

    rendered = await render_isolated(book(), tick=tick)

    assert rendered.content.startswith(b"%PDF")
    assert ticks >= 1


async def test_endless_render_is_stopped() -> None:
    with pytest.raises(ExportError, match="не собрался"):
        await render_isolated(book(), limit_seconds=0)
