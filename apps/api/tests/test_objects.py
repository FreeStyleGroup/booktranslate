"""Специальные объекты главы: коды, оригиналы, упоминания, новые версии мастера."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import masters as masters_module
from app.services.parsers import ParsedBlock, ParsedItem
from app.services.parsers.markup import EpubParser
from tests.conftest import requires_database
from tests.factories import Account, create_project, epub_bytes, png_bytes, register

FIRST = (
    "<h1>1 Basics</h1>"
    "<p>The loss is shown in Figure 1.1 and listed in <a href='#t11'>Table 1.1</a>.</p>"
    '<figure id="f11"><img src="img/loss.png" alt="Loss"/>'
    "<figcaption>Figure 1.1. Loss curve</figcaption></figure>"
    '<table id="t11"><caption>Table 1.1: Pumps</caption>'
    '<tr><th colspan="2">Pump</th></tr><tr><td>P-101</td><td>10 bar</td></tr></table>'
    '<p><math display="block"><mi>E</mi><mo>=</mo><mi>m</mi></math> (1.2)</p>'
    '<pre class="language-python">\nprint("hi")\n</pre>'
)
SECOND = "<h1>2 Results</h1><p>Compare with Figure 1.1 from the first chapter.</p>"
DRAWING = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><script>alert(1)</script></svg>'
)


async def book_with_objects(client: AsyncClient, account: Account) -> tuple[str, list[dict]]:
    """Книга EPUB из двух глав с рисунком, таблицей, формулой и листингом в первой."""
    project_id = await create_project(client, account)
    created = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "Pumps"}
    )
    book_id: str = created.json()["id"]

    source = epub_bytes(
        [("part01.xhtml", FIRST), ("part02.xhtml", SECOND + DRAWING)],
        assets={"img/loss.png": png_bytes()},
    )
    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("pumps.epub", source, "application/epub+zip")},
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    for step in ("proposal", "approval"):
        response = await client.post(f"/books/{book_id}/chapters/{step}", headers=account.headers)
        assert response.status_code == 200, response.text

    chapters: list[dict] = response.json()["chapters"]
    return book_id, chapters


async def extract(
    client: AsyncClient, account: Account, chapter_id: str, reason: str | None = None
) -> dict:
    response = await client.post(
        f"/chapters/{chapter_id}/masters", headers=account.headers, json={"reason": reason}
    )
    assert response.status_code == 201, response.text

    master: dict = response.json()
    return master


async def objects_of(
    client: AsyncClient, account: Account, master_id: str, kind: str | None = None
) -> list[dict]:
    query = f"?type={kind}" if kind else ""
    response = await client.get(f"/masters/{master_id}/objects{query}", headers=account.headers)
    assert response.status_code == 200, response.text

    items: list[dict] = response.json()
    return items


@requires_database
async def test_objects_get_codes_of_their_own_kind(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, (master, objects) = await approved_book_master(db_client, account)

    assert master["object_count"] == 4
    assert [(item["full_code"], item["type"], item["label"]) for item in objects] == [
        ("CH01-FIG001", "figure", "1.1"),
        ("CH01-TBL001", "table", "1.1"),
        ("CH01-EQ001", "equation", "1.2"),
        ("CH01-CODE001", "code", None),
    ]

    figure, table, equation, listing = objects
    assert figure["caption"] == "Figure 1.1. Loss curve"
    assert figure["payload"]["images"][0]["media_type"] == "image/png"
    assert table["payload"]["cols"] == 2
    assert len(table["content_codes"]) == 3
    # Запись формулы как есть — только в карточке, вкладке хватает дерева.
    assert "raw" not in equation["payload"]
    assert equation["payload"]["preview"][0] == "math"
    assert len(listing["content_codes"]) == 1

    only_tables = await objects_of(db_client, account, master["id"], "table")
    assert [item["code"] for item in only_tables] == ["TBL001"]


async def approved_book_master(
    client: AsyncClient, account: Account
) -> tuple[str, tuple[dict, list[dict]]]:
    book_id, chapters = await book_with_objects(client, account)
    master = await extract(client, account, chapters[0]["id"])

    return book_id, (master, await objects_of(client, account, master["id"]))


@requires_database
async def test_figure_original_is_served_as_an_image_and_nothing_more(
    db_client: AsyncClient,
) -> None:
    account = await register(db_client)
    _, (_, objects) = await approved_book_master(db_client, account)
    figure = objects[0]

    response = await db_client.get(f"/objects/{figure['id']}/images/0", headers=account.headers)

    assert response.status_code == 200
    assert response.content == png_bytes()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]

    missing = await db_client.get(f"/objects/{figure['id']}/images/5", headers=account.headers)
    assert missing.status_code == 404


@requires_database
async def test_svg_drawing_keeps_its_scripts_locked(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await book_with_objects(db_client, account)
    master = await extract(db_client, account, chapters[1]["id"])
    [drawing] = await objects_of(db_client, account, master["id"], "figure")

    response = await db_client.get(f"/objects/{drawing['id']}/images/0", headers=account.headers)

    # Оригинал — как был, со скриптом: правка оригинала не наша работа.
    # Выполниться ему не даёт политика, а не вырезание.
    assert response.content == DRAWING.encode()
    assert response.headers["content-type"] == "image/svg+xml"
    assert "sandbox" in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]


@requires_database
async def test_object_card_shows_content_caption_and_mentions(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await book_with_objects(db_client, account)
    await extract(db_client, account, chapters[0]["id"])
    second = await extract(db_client, account, chapters[1]["id"])
    versions = await db_client.get(
        f"/chapters/{chapters[0]['id']}/masters", headers=account.headers
    )
    figure, table, *_ = await objects_of(db_client, account, versions.json()[0]["id"])

    card = await db_client.get(f"/objects/{table['id']}", headers=account.headers)
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["caption_block"]["text"] == "Table 1.1: Pumps"
    assert [(cell["text"], cell["row"], cell["column"]) for cell in body["content"]] == [
        ("Pump", 0, 0),
        ("P-101", 1, 0),
        ("10 bar", 1, 1),
    ]
    # Ссылка на якорь таблицы — упоминание надёжное.
    assert [(item["kind"], item["phrase"]) for item in body["mentions"]] == [("link", "Table 1.1")]

    # Рисунок упомянут в своей главе и из второй — та извлечена позже, и
    # связь появилась при её извлечении.
    figure_card = (await db_client.get(f"/objects/{figure['id']}", headers=account.headers)).json()
    assert [item["chapter_id"] for item in figure_card["mentions"]] == [
        chapters[0]["id"],
        chapters[1]["id"],
    ]
    assert figure_card["master_label"] == "v1"
    assert second["object_count"] == 1


@requires_database
async def test_objects_are_found_by_code(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book_id, (_, objects) = await approved_book_master(db_client, account)

    in_book = await db_client.get(f"/books/{book_id}/objects/ch01-tbl001", headers=account.headers)
    assert in_book.status_code == 200
    assert in_book.json()["object_id"] == objects[1]["id"]

    anywhere = await db_client.get(
        "/objects/lookup", params={"code": "BK01-CH01-EQ001"}, headers=account.headers
    )
    assert anywhere.status_code == 200
    assert anywhere.json()["full_code"] == "CH01-EQ001"

    wrong = await db_client.get(f"/books/{book_id}/objects/FIG-1", headers=account.headers)
    assert wrong.status_code == 400
    absent = await db_client.get(f"/books/{book_id}/objects/CH01-FIG009", headers=account.headers)
    assert absent.status_code == 404


class _RevisedTable:
    """Разборщик «после исправления»: в таблице поправлено давление."""

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        for item in EpubParser().parse(path):
            if isinstance(item, ParsedBlock) and item.text == "10 bar":
                item.text = "12 bar"
            yield item


@requires_database
async def test_changed_table_is_a_new_object_and_the_rest_keep_codes(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    _, chapters = await book_with_objects(db_client, account)
    first = await extract(db_client, account, chapters[0]["id"])
    before = await objects_of(db_client, account, first["id"])

    monkeypatch.setattr(masters_module, "parser_for", lambda _format: _RevisedTable())
    second = await extract(db_client, account, chapters[0]["id"], reason="Давление в таблице 1.1")
    after = await objects_of(db_client, account, second["id"])

    assert [item["code"] for item in after] == ["FIG001", "TBL002", "EQ001", "CODE001"]
    assert after[0]["id"] == before[0]["id"]

    revised = (await db_client.get(f"/objects/{after[1]['id']}", headers=account.headers)).json()
    assert revised["parent_code"] == "CH01-TBL001"

    # Прежняя таблица выведена из действия, но в первой версии — такая, какой была.
    old = await db_client.get(
        f"/objects/{before[1]['id']}", params={"master_id": first["id"]}, headers=account.headers
    )
    assert old.json()["active"] is False
    assert [cell["text"] for cell in old.json()["content"]][-1] == "10 bar"
    # Без версии выведенный объект показывается в последней, где он был.
    latest = await db_client.get(f"/objects/{before[1]['id']}", headers=account.headers)
    assert latest.json()["master_id"] == first["id"]


@requires_database
async def test_objects_are_invisible_to_another_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    book_id, (master, objects) = await approved_book_master(db_client, owner)
    stranger = await register(
        db_client, email="stranger@example.com", organization_name="Чужая контора"
    )

    for url in (
        f"/masters/{master['id']}/objects",
        f"/objects/{objects[0]['id']}",
        f"/objects/{objects[0]['id']}/images/0",
        f"/books/{book_id}/objects/CH01-FIG001",
    ):
        response = await db_client.get(url, headers=stranger.headers)
        assert response.status_code == 404, url

    lookup = await db_client.get(
        "/objects/lookup", params={"code": "BK01-CH01-FIG001"}, headers=stranger.headers
    )
    assert lookup.status_code == 404
