"""PDF выпуска: содержание то же, что у DOCX, вёрстка своя.

Движок — WeasyPrint. Выбран вместо LibreOffice осознанно: конвертер офисных файлов разбирает чужой
документ со всеми его связями (внешние картинки, вложенные файлы), и на площадке с многими
заказчиками это путь к чтению файлов и запросам изнутри сервера. Здесь на вход идёт только наш
собственный HTML: весь текст экранирован, а изображения отдаёт закрытый загрузчик из заранее
собранного набора. Сеть и файловая система ему недоступны.

Сборка идёт в отдельном процессе с пределом времени и памяти. Рисунок из книги бывает SVG, а его
разбор может уйти в бесконечность: поток из такого не вытащить, а процесс снимается. Иначе один
файл одного заказчика остановил бы очередь для всех.

Страницы для аудита рисует pypdfium2: только наши PDF, на витрину уходит обычная картинка, поэтому
стороннего просмотрщика в браузере нет.
"""

import asyncio
import html
import io
import json
import logging
import multiprocessing
import re
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2

from app.models.block import BlockKind
from app.services.export.base import ExportError
from app.services.export.document import (
    Element,
    FigureElement,
    FormulaElement,
    PublicationDocument,
    TableElement,
    TextElement,
)

logger = logging.getLogger(__name__)

MEDIA_TYPE = "application/pdf"
SUFFIX = ".pdf"

# Версия нашей вёрстки: стили и разметка меняют файл так же, как и версия движка.
LAYOUT_VERSION = "2026.11.1"
STUB_RENDERER = "stub"

RENDER_TIMEOUT_SECONDS = 15 * 60
# Ниже предела контейнера рабочего: иначе память кончится у всего контейнера, а не у этой сборки.
MEMORY_LIMIT_BYTES = 1536 * 1024 * 1024
TICK_SECONDS = 15

# Страница для глаза: около 115 точек на дюйм, хватает, чтобы читать и заметить сбитую таблицу.
PAGE_SCALE = 1.6

BLANK_CHECK_SCALE = 0.5
BLANK_LEVEL = 245

STUB_ELEMENTS_PER_PAGE = 3
STUB_PAGE_SIZE = (595, 842)

_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

_CSS = """
@page {
  size: A4;
  margin: 22mm 20mm 24mm;
  @bottom-center { content: counter(page); font: 10pt "Liberation Serif", serif; color: #555; }
}
@page :first { @bottom-center { content: none; } }
html { font: 11pt/1.45 "Liberation Serif", "DejaVu Serif", serif; color: #111; }
.cover { break-after: page; padding-top: 70mm; text-align: center; }
.cover h1 { font-size: 26pt; line-height: 1.2; break-before: auto; }
.toc { break-after: page; }
.toc h2 { font-size: 16pt; break-before: auto; }
.toc ul { list-style: none; margin: 0; padding: 0; }
.toc li { margin: 3pt 0; }
.toc .level-2 { padding-left: 14pt; font-size: 10pt; }
.toc a { color: inherit; text-decoration: none; }
.toc a::after { content: leader(dotted) " " target-counter(attr(href), page); }
h1, h2, h3, h4, h5, h6 { font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
  line-height: 1.25; break-after: avoid; margin: 16pt 0 8pt; }
h1 { font-size: 18pt; break-before: page; }
h2 { font-size: 14pt; } h3 { font-size: 12pt; } h4, h5, h6 { font-size: 11pt; }
p { margin: 0 0 7pt; text-align: justify; orphans: 2; widows: 2; }
ul.list { margin: 0 0 7pt 16pt; padding: 0; }
.warning { padding: 6pt 8pt; border-left: 3pt solid #b45309; background: #fef3c7;
  font-weight: 600; }
.caption { font-style: italic; font-size: 10pt; text-align: left; }
pre { font: 8.5pt/1.35 "DejaVu Sans Mono", monospace; white-space: pre-wrap;
  overflow-wrap: anywhere; background: #f5f5f5; padding: 6pt 8pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.5pt; }
td, th { border: 0.5pt solid #777; padding: 3pt 5pt; vertical-align: top; text-align: left;
  overflow-wrap: anywhere; }
th { background: #eee; font-weight: 600; }
figure { margin: 8pt 0; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; max-height: 210mm; }
.formula { text-align: center; font-style: italic; margin: 6pt 0 10pt; }
"""


@dataclass(frozen=True, slots=True)
class RenderedPdf:
    content: bytes
    # На каждую страницу: какие блоки на ней стоят. По этому страница находит своё замечание.
    page_map: list[list[str]]
    renderer: str


def _anchors(document: PublicationDocument) -> dict[str, str]:
    """Адреса блоков внутри файла. Порядковые: идентификаторы из базы в файл читателя не идут."""
    names: dict[str, str] = {}

    for element in document.elements:
        if isinstance(element, TextElement):
            names[element.block_id] = f"p{len(names)}"
        elif isinstance(element, TableElement):
            for row in element.rows:
                for cell in row:
                    if cell.block_id is not None:
                        names[cell.block_id] = f"p{len(names)}"

    return names


def build_html(document: PublicationDocument) -> str:
    """Разметка книги. Всё из книги экранируется: сырой разметки исходника здесь нет."""
    language = document.language if _LANGUAGE.match(document.language) else "ru"
    title = html.escape(document.title)
    anchors = _anchors(document)
    parts = [
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">',
        f"<title>{title}</title><style>{_CSS}</style></head><body>",
        f'<section class="cover"><h1>{title}</h1></section>',
    ]

    if document.toc:
        parts.append('<nav class="toc"><h2>Оглавление</h2><ul>')
        for entry in document.toc:
            parts.append(
                f'<li class="level-{min(entry.level, 2)}">'
                f'<a href="#{anchors[entry.block_id]}">{html.escape(entry.text)}</a></li>'
            )
        parts.append("</ul></nav>")

    parts.append("<main>")
    for element in document.elements:
        parts.append(_element(element, anchors))
    parts.append("</main></body></html>")

    return "".join(parts)


def _element(element: Element, anchors: dict[str, str]) -> str:
    if isinstance(element, TableElement):
        return _table(element, anchors)
    if isinstance(element, FigureElement):
        images = "".join(
            f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(alt, quote=True)}">'
            for url, alt in zip(element.urls, element.alts, strict=True)
        )
        return f"<figure>{images}</figure>"
    if isinstance(element, FormulaElement):
        return f'<p class="formula">{html.escape(element.text)}</p>'

    anchor = f'id="{anchors[element.block_id]}"'
    text = html.escape(element.text)

    if element.kind is BlockKind.HEADING:
        level = min(max(element.level, 1), 6)
        return f"<h{level} {anchor}>{text}</h{level}>"
    if element.kind is BlockKind.CODE:
        return f"<pre {anchor}>{text}</pre>"
    if element.kind is BlockKind.LIST_ITEM:
        return f'<ul class="list" {anchor}><li>{text}</li></ul>'
    if element.kind is BlockKind.WARNING:
        return f'<p class="warning" {anchor}>{text}</p>'
    if element.kind is BlockKind.CAPTION:
        return f'<p class="caption" {anchor}>{text}</p>'

    return f"<p {anchor}>{text}</p>"


def _table(element: TableElement, anchors: dict[str, str]) -> str:
    rows: list[str] = []

    for row in element.rows:
        cells: list[str] = []
        for cell in row:
            tag = "th" if cell.header else "td"
            spans = ""
            if cell.rowspan > 1:
                spans += f' rowspan="{cell.rowspan}"'
            if cell.colspan > 1:
                spans += f' colspan="{cell.colspan}"'
            anchor = f' id="{anchors[cell.block_id]}"' if cell.block_id is not None else ""
            text = html.escape(cell.text).replace("\n", "<br>")
            cells.append(f"<{tag}{spans}{anchor}>{text}</{tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"<table>{''.join(rows)}</table>"


def _render_with_weasyprint(document: PublicationDocument) -> RenderedPdf:
    # Импорт здесь, а не в начале модуля: движку нужны системные библиотеки Pango, а API без них
    # должен работать: PDF собирает только рабочий процесс.
    import weasyprint
    from weasyprint.urls import FatalURLFetchingError, URLFetcher, URLFetcherResponse

    images = document.images

    class ClosedFetcher(URLFetcher):  # type: ignore[misc]
        """Только изображения из набора. Ни файлов, ни сети."""

        def fetch(self, url: str, headers: Any = None) -> URLFetcherResponse:
            found = images.get(url)
            if found is None:
                raise FatalURLFetchingError(f"Обращение за пределы выпуска: {url[:80]}")

            return URLFetcherResponse(url, found[0], {"Content-Type": found[1]})

    rendered = weasyprint.HTML(string=build_html(document), url_fetcher=ClosedFetcher()).render()
    blocks = {name: block_id for block_id, name in _anchors(document).items()}
    page_map = [
        sorted(blocks[name] for name in page.anchors if name in blocks) for page in rendered.pages
    ]

    return RenderedPdf(
        content=rendered.write_pdf(),
        page_map=page_map,
        renderer=f"weasyprint-{weasyprint.__version__}/{LAYOUT_VERSION}",
    )


def _child(document: PublicationDocument, folder: str) -> None:
    """Точка входа отдельного процесса. Результат в файлах: PDF в трубу не положить."""
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))

    target = Path(folder)

    # Предел здесь, а не в родителе: снять можно только сам процесс сборки.
    try:
        rendered = _render_with_weasyprint(document)
    except BaseException as error:
        (target / "error.txt").write_text(f"{type(error).__name__}: {error}", encoding="utf-8")
        raise

    (target / "out.pdf").write_bytes(rendered.content)
    (target / "meta.json").write_text(
        json.dumps({"page_map": rendered.page_map, "renderer": rendered.renderer}),
        encoding="utf-8",
    )


async def render_isolated(
    document: PublicationDocument,
    *,
    tick: Callable[[], Awaitable[None]] | None = None,
    limit_seconds: float = RENDER_TIMEOUT_SECONDS,
) -> RenderedPdf:
    """Собрать PDF в отдельном процессе. `tick` зовётся, пока идёт сборка: признак жизни."""
    context = multiprocessing.get_context("spawn")

    with tempfile.TemporaryDirectory(prefix="booktranslate-pdf-") as folder:
        process = context.Process(target=_child, args=(document, folder), daemon=True)
        process.start()

        # Отмена и сбой тоже снимают процесс: иначе он доедал бы память уже без хозяина.
        try:
            waited = 0.0
            while process.is_alive():
                if waited >= limit_seconds:
                    raise ExportError(f"PDF не собрался за {int(limit_seconds)} секунд")

                await asyncio.to_thread(process.join, TICK_SECONDS)
                waited += TICK_SECONDS
                if tick is not None:
                    await tick()
        finally:
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, TICK_SECONDS)

        target = Path(folder)
        if process.exitcode != 0 or not (target / "out.pdf").exists():
            problem = target / "error.txt"
            reason = problem.read_text(encoding="utf-8") if problem.exists() else "процесс снят"
            # Причина для разбора в журнале: на экран текст движка не идёт.
            logger.warning("Сборка PDF: %s", reason[:2000])
            raise ExportError("PDF не собрался: сверстать файл не удалось")

        meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))

        return RenderedPdf(
            content=(target / "out.pdf").read_bytes(),
            page_map=meta["page_map"],
            renderer=meta["renderer"],
        )


def render_stub(document: PublicationDocument) -> RenderedPdf:
    """Заглушка для тестов и стенда без Pango: настоящий PDF с пустыми страницами."""
    anchored = [
        [element.block_id] for element in document.elements if isinstance(element, TextElement)
    ]
    pages = [
        [row[0] for row in anchored[start : start + STUB_ELEMENTS_PER_PAGE]]
        for start in range(0, max(len(anchored), 1), STUB_ELEMENTS_PER_PAGE)
    ]
    pdf = pypdfium2.PdfDocument.new()
    try:
        for _ in pages:
            pdf.new_page(*STUB_PAGE_SIZE).close()
        buffer = io.BytesIO()
        pdf.save(buffer)
    finally:
        pdf.close()

    return RenderedPdf(content=buffer.getvalue(), page_map=pages, renderer=STUB_RENDERER)


def page_count(content: bytes) -> int:
    pdf = pypdfium2.PdfDocument(content)
    try:
        return len(pdf)
    finally:
        pdf.close()


def page_png(content: bytes | Path, page_no: int) -> bytes:
    """Страница картинкой, нумерация с единицы. Только наши собственные PDF."""
    pdf = pypdfium2.PdfDocument(content)
    try:
        page = pdf[page_no - 1]
        try:
            # Страница из чужих рисунков бывает любой: файл наш, а содержимое нет.
            bitmap = page.render(scale=PAGE_SCALE)
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
        finally:
            page.close()
    finally:
        pdf.close()

    return buffer.getvalue()


def page_is_blank(content: bytes, page_no: int) -> bool:
    """Пустая ли страница. Мелкого масштаба хватает: важно, есть ли на ней хоть что-то тёмное."""
    pdf = pypdfium2.PdfDocument(content)
    try:
        page = pdf[page_no - 1]
        try:
            darkest = page.render(scale=BLANK_CHECK_SCALE).to_pil().convert("L").getextrema()[0]
        finally:
            page.close()
    finally:
        pdf.close()

    return bool(darkest > BLANK_LEVEL)


def text_layer(content: bytes) -> str:
    """Весь текст PDF: на нём проверяется, что служебное не попало в файл читателя."""
    pdf = pypdfium2.PdfDocument(content)
    parts: list[str] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    parts.append(textpage.get_text_range())
                finally:
                    textpage.close()
            finally:
                page.close()
    finally:
        pdf.close()

    return "\n".join(parts)
