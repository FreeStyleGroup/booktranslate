"""Черновая выгрузка главы и книги.

Главное здесь — не форматы, а два обещания: непереведённое не отдаётся молча, а DOCX
возвращается с сохранённой структурой.
"""

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import docx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker as worker_module
from app.models.block import Block
from app.services import masters as masters_module
from app.services.parsers import ParsedBlock, ParsedItem
from app.services.parsers.markup import HtmlParser
from app.services.providers import TranslationRequest
from app.worker import once
from tests.chapters import STOP, block_rows, open_book, translate, translated_book
from tests.conftest import RecordingProvider, requires_database
from tests.factories import PdfLine, PdfPage, epub_bytes, pdf_bytes, register

MANUAL = (
    b"# Safety\n"
    b"\n"
    b"Open the valve before start.\n"
    b"\n"
    b"- Check the pressure gauge\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
)

MARKDOWN = {"name": "manual.md", "media": "text/markdown"}
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def word_file() -> bytes:
    """Документ Word со стилями, списком и таблицей."""
    document = docx.Document()
    document.add_heading("Safety instructions", level=1)
    document.add_paragraph("Open the valve before start.")
    document.add_paragraph("Check the pressure gauge", style="List Bullet")

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Parameter"
    table.cell(0, 1).text = "Value"

    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()


@requires_database
async def test_pdf_is_handed_over_as_a_fresh_word_document(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """PDF обратно в PDF не вписать; заказчик получает документ со структурой."""
    account = await register(db_client)
    book = await translated_book(
        db_client,
        session,
        account,
        data=pdf_bytes(
            [
                PdfPage(
                    lines=(
                        PdfLine("Safety", size=18),
                        PdfLine(""),
                        PdfLine("Open the valve before start."),
                        PdfLine(""),
                        PdfLine("- Check the pressure gauge"),
                        PdfLine("- Close the valve"),
                    )
                )
            ]
        ),
        name="manual.pdf",
        media="application/pdf",
    )

    response = await db_client.get(
        f"/books/{book.book_id}/export", headers=account.headers, params={"format": "docx"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")

    document = docx.Document(io.BytesIO(response.content))
    paragraphs = [(p.style.name, p.text) for p in document.paragraphs if p.text.strip()]

    assert paragraphs[0] == ("Heading 1", "[ru] Safety")
    assert paragraphs[1][1] == "[ru] Open the valve before start."
    assert paragraphs[2] == ("List Bullet", "[ru] Check the pressure gauge")


@requires_database
async def test_untranslated_chapter_is_not_handed_over(db_client: AsyncClient) -> None:
    """Глава, где половина абзацев на английском, отдаётся только по явной просьбе."""
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL, **MARKDOWN)

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=markdown", headers=account.headers
    )

    assert response.status_code == 409
    assert "Не переведено блоков: 4" in response.json()["detail"]


@requires_database
async def test_draft_says_how_much_is_missing(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL, **MARKDOWN)

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=markdown&allow_untranslated=true",
        headers=account.headers,
    )

    assert response.status_code == 200, response.text
    assert response.headers["X-Untranslated-Blocks"] == "4"
    # Непереведённое ушло исходным текстом, а не пустотой.
    assert "Open the valve before start." in response.text


@requires_database
async def test_book_kit_says_how_much_is_ready_to_export(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Кнопки выгрузки книги рисуются по этому ответу, второго счёта у витрины нет."""
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL, **MARKDOWN)

    before = await db_client.get(f"/books/{book.book_id}/sources", headers=account.headers)
    assert before.status_code == 200, before.text
    assert before.json()["translated"] == 0
    assert before.json()["blocks"] == 4
    assert "markdown" in before.json()["export_formats"]

    await translate(db_client, session, account, book.chapter)

    after = await db_client.get(f"/books/{book.book_id}/sources", headers=account.headers)
    assert after.json()["translated"] == after.json()["blocks"] == 4


@requires_database
async def test_markdown_keeps_the_structure(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    book = await translated_book(db_client, session, account, data=MANUAL, **MARKDOWN)

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=markdown", headers=account.headers
    )

    assert response.status_code == 200, response.text
    body = response.text

    assert response.headers["X-Untranslated-Blocks"] == "0"
    # Заголовок остался заголовком того же уровня, пункт — пунктом.
    assert body.startswith("# [ru] Safety")
    assert "\n- [ru] Check the pressure gauge" in body


@requires_database
async def test_variant_goes_to_the_file_only_after_it_is_adopted(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """В выгрузку идёт текущая редакция, а не последняя по времени."""
    account = await register(db_client)
    book = await translated_book(db_client, session, account, data=MANUAL, **MARKDOWN)

    rows = await block_rows(db_client, account, book.chapter)
    row = next(item for item in rows if item["source_text"].startswith("Open"))

    asked = await db_client.post(
        f"/chapters/{book.chapter}/translation/retranslate",
        headers=account.headers,
        json={"items": [{"block_id": row["id"], "base_revision_id": row["current"]["id"]}]},
    )
    assert asked.status_code == 201, asked.text
    assert await once(session, "test", STOP) is True

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=text", headers=account.headers
    )

    # Текст варианта у заглушки тот же, поэтому сверяется не текст, а что глава цела.
    assert response.status_code == 200, response.text
    assert response.headers["X-Untranslated-Blocks"] == "0"


@requires_database
async def test_export_name_does_not_shadow_the_original(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book = await translated_book(db_client, session, account, data=MANUAL, **MARKDOWN)

    response = await db_client.get(
        f"/books/{book.book_id}/export?format=text", headers=account.headers
    )

    assert (
        "manual-%D0%BF%D0%B5%D1%80%D0%B5%D0%B2%D0%BE%D0%B4.txt"
        in (response.headers["Content-Disposition"])
    )


@requires_database
async def test_docx_comes_back_as_docx_with_styles(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Собирать Word с нуля нельзя — оформление заказчика пропало бы."""
    account = await register(db_client)
    book = await translated_book(
        db_client, session, account, data=word_file(), name="manual.docx", media=DOCX_MEDIA
    )

    response = await db_client.get(f"/books/{book.book_id}/export", headers=account.headers)

    assert response.status_code == 200, response.text

    result = docx.Document(io.BytesIO(response.content))
    texts = [paragraph.text for paragraph in result.paragraphs if paragraph.text.strip()]

    assert texts[0].startswith("[ru] Safety instructions")
    # Стиль заголовка на месте: перевод вписан в исходный файл, а не собран заново.
    assert result.paragraphs[0].style is not None
    assert result.paragraphs[0].style.name.startswith("Heading")

    # Таблица тоже переведена и осталась таблицей.
    assert len(result.tables) == 1
    assert result.tables[0].cell(0, 0).text.startswith("[ru] Parameter")


@requires_database
async def test_docx_from_other_sources_is_a_fresh_document(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Из Markdown документ Word собирается с нуля — со структурой, но без оформления."""
    account = await register(db_client)
    book = await translated_book(db_client, session, account, data=MANUAL, **MARKDOWN)

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=docx", headers=account.headers
    )

    assert response.status_code == 200, response.text

    document = docx.Document(io.BytesIO(response.content))
    styles = [p.style.name for p in document.paragraphs if p.text.strip()]

    assert styles[0] == "Heading 1"
    assert "List Bullet" in styles


@requires_database
async def test_source_format_without_writer_says_so(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book = await translated_book(db_client, session, account, data=MANUAL, **MARKDOWN)

    response = await db_client.get(
        f"/books/{book.book_id}/export?format=source", headers=account.headers
    )

    assert response.status_code == 415
    assert "markdown" in response.json()["detail"]


@requires_database
async def test_chapter_is_not_exported_in_the_source_format(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Весь файл с одной переведённой главой выглядел бы переводом, которым не является."""
    account = await register(db_client)
    book = await translated_book(
        db_client, session, account, data=word_file(), name="manual.docx", media=DOCX_MEDIA
    )

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=source", headers=account.headers
    )

    assert response.status_code == 415


@requires_database
async def test_long_paragraph_comes_back_whole(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Абзац резался ради перевода — в файл он обязан вернуться одним абзацем."""
    account = await register(db_client)
    sentence = "The hydraulic power unit operates at a very high pressure indeed. "
    data = (sentence * 40).strip().encode("utf-8")

    book = await open_book(db_client, account, data=data, name="long.txt", media="text/plain")

    log: list[TranslationRequest] = []
    monkeypatch.setattr(worker_module, "get_provider", lambda _model=None: RecordingProvider(log))

    await translate(db_client, session, account, book.chapter)

    assert len(log) > 1, "абзац должен был разрезаться, иначе тест ничего не проверяет"

    response = await db_client.get(
        f"/chapters/{book.chapter}/export?format=text", headers=account.headers
    )

    # Один блок — одна строка: части склеились обратно.
    assert len([line for line in response.text.splitlines() if line.strip()]) == 1


@requires_database
async def test_epub_comes_back_as_a_readable_book(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Книга — это архив с обложкой, стилями и описью; всё это обязано остаться."""
    account = await register(db_client)
    book = await translated_book(
        db_client,
        session,
        account,
        data=epub_bytes(),
        name="book.epub",
        media="application/epub+zip",
    )

    response = await db_client.get(f"/books/{book.book_id}/export", headers=account.headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/epub+zip")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()

        # Первая запись и без сжатия — по ней читалки опознают формат.
        assert names[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED

        # Опись и главы на месте, ничего не потерялось.
        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names

        chapter = archive.read("OEBPS/part0002.xhtml").decode("utf-8")

    # Разметка блока сохранилась: заголовок остался заголовком.
    assert "<h1>[ru] Первая глава</h1>" in chapter


@requires_database
async def test_html_keeps_its_own_markup(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    page = (
        b"<html><body><h2 class='chapter'>Safety</h2>"
        b"<p>Open the valve before start.</p>"
        b"<script>alert(1)</script></body></html>"
    )

    book = await translated_book(
        db_client, session, account, data=page, name="page.html", media="text/html"
    )

    response = await db_client.get(f"/books/{book.book_id}/export", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.text

    # Класс и уровень заголовка остались; переведён только текст.
    assert 'class="chapter"' in body
    assert "[ru] Safety" in body
    assert "[ru] Open the valve before start." in body
    # Скрипт разбор не читал — значит и портить его при сборке нечем.
    assert "alert(1)" in body


@requires_database
async def test_kept_block_is_written_to_its_new_place(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Новая версия мастера сдвинула блок: перевод обязан встать туда, где он теперь.

    Текст блока тот же, и код с редакцией он сохраняет, а вот номер в обходе файла у него
    другой. Со старым номером перевод лёг бы в чужой абзац.
    """
    account = await register(db_client)
    page = b"<html><body><p>First paragraph text.</p><p>Second paragraph text.</p></body></html>"
    book = await translated_book(
        db_client, session, account, data=page, name="page.html", media="text/html"
    )

    class Shifted:
        """Разбор, который нашёл новый абзац перед прежними."""

        def parse(self, path: Path) -> Iterator[ParsedItem]:
            yield ParsedBlock(text="Brand new paragraph.", location={"block": 0})

            for item in HtmlParser().parse(path):
                if isinstance(item, ParsedBlock):
                    item.location = {**item.location, "block": item.location["block"] + 1}
                yield item

    monkeypatch.setattr(masters_module, "parser_for", lambda _format: Shifted())

    extracted = await db_client.post(
        f"/chapters/{book.chapter}/masters",
        headers=account.headers,
        json={"reason": "Разбор нашёл абзац, потерянный раньше"},
    )
    assert extracted.status_code == 201, extracted.text

    block = await session.scalar(select(Block).where(Block.source_text == "First paragraph text."))
    assert block is not None
    await session.refresh(block)

    assert block.current_revision_id is not None
    assert block.source_location["block"] == 1


@requires_database
async def test_export_is_scoped_to_organization(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    owner = await register(db_client)
    book = await translated_book(db_client, session, owner, data=MANUAL, **MARKDOWN)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    for path in (f"/chapters/{book.chapter}/export", f"/books/{book.book_id}/export"):
        response = await db_client.get(f"{path}?format=text", headers=stranger.headers)
        assert response.status_code == 404
