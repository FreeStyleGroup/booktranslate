"""Мастер главы и блоки: извлечение, версии, коды, поиск."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.models.organization import Membership, Role
from app.services import masters as masters_module
from app.services.block_reconcile import PlacedEntry, master_checksum
from app.services.parsers import ParsedBlock, ParsedItem
from app.services.parsers.markup import HtmlParser
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

BOOK = (
    b"<h2>1 Introduction</h2>"
    b"<p>First paragraph.</p>"
    b"<p>Second paragraph. It has two sentences.</p>"
    b"<pre>\ndef entropy(p):\n    return -sum(p * log(p))\n</pre>"
    b"<h2>2 Denoising</h2>"
    b"<p>Noise.</p>"
)


async def approved_book(client: AsyncClient, account: Account) -> tuple[str, list[dict]]:
    """Книга с основным источником и утверждёнными главами."""
    project_id = await create_project(client, account)
    created = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "ML"}
    )
    book_id: str = created.json()["id"]

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("book.html", BOOK, "text/html")},
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    proposed = await client.post(f"/books/{book_id}/chapters/proposal", headers=account.headers)
    assert proposed.status_code == 200, proposed.text
    approved = await client.post(f"/books/{book_id}/chapters/approval", headers=account.headers)
    assert approved.status_code == 200, approved.text

    chapters: list[dict] = approved.json()["chapters"]
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


async def blocks_of(client: AsyncClient, account: Account, master_id: str) -> list[dict]:
    response = await client.get(f"/masters/{master_id}/blocks", headers=account.headers)
    assert response.status_code == 200, response.text

    items: list[dict] = response.json()["items"]
    return items


@requires_database
async def test_first_master_gives_blocks_permanent_codes(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)

    master = await extract(db_client, account, chapters[0]["id"])

    assert master["version"] == 1
    assert master["label"] == "v1"
    assert master["reason"] is None
    assert master["block_count"] == 4
    assert len(master["checksum"]) == 64

    blocks = await blocks_of(db_client, account, master["id"])
    assert [block["full_code"] for block in blocks] == [
        "CH01-B0001",
        "CH01-B0002",
        "CH01-B0003",
        "CH01-B0004",
    ]
    assert all(block["chunks"] >= 1 for block in blocks)


@requires_database
async def test_master_keeps_code_listing_verbatim(db_client: AsyncClient) -> None:
    """Отступ в листинге — текст мастера: извлечение его не трогает."""
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)

    master = await extract(db_client, account, chapters[0]["id"])
    blocks = await blocks_of(db_client, account, master["id"])

    code = next(block for block in blocks if block["kind"] == "code")
    assert code["source_text"] == "def entropy(p):\n    return -sum(p * log(p))"


@requires_database
async def test_master_needs_approved_boundaries(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    created = await db_client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "ML"}
    )
    book_id = created.json()["id"]
    await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("book.html", BOOK, "text/html")},
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    proposed = await db_client.post(f"/books/{book_id}/chapters/proposal", headers=account.headers)
    draft = proposed.json()["chapters"][0]

    response = await db_client.post(
        f"/chapters/{draft['id']}/masters", headers=account.headers, json={}
    )

    assert response.status_code == 409
    assert "не утверждены" in response.json()["detail"]


@requires_database
async def test_unchanged_text_gives_no_new_version(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)
    await extract(db_client, account, chapters[0]["id"])

    again = await db_client.post(
        f"/chapters/{chapters[0]['id']}/masters",
        headers=account.headers,
        json={"reason": "Проверяем, что ничего не поменялось"},
    )

    assert again.status_code == 409
    assert "не изменился" in again.json()["detail"]


@requires_database
async def test_new_version_needs_a_reason(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)
    await extract(db_client, account, chapters[0]["id"])

    response = await db_client.post(
        f"/chapters/{chapters[0]['id']}/masters", headers=account.headers, json={}
    )

    assert response.status_code == 400
    assert "причины" in response.json()["detail"]


class _FixedParser:
    """Разборщик «после исправления»: второй абзац поправлен, третий разделён.

    Файлы в сервисе неизменяемы, поэтому новая версия мастера в жизни
    появляется, когда меняется разбор. Здесь он и меняется — поверх
    настоящего разбора того же файла.
    """

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        for block in HtmlParser().parse(path):
            if not isinstance(block, ParsedBlock):
                yield block
            elif block.text == "First paragraph.":
                yield ParsedBlock(
                    text="First paragraph, corrected.", kind=block.kind, location=block.location
                )
            elif block.text.startswith("Second paragraph."):
                yield ParsedBlock(
                    text="Second paragraph.", kind=block.kind, location=block.location
                )
                yield ParsedBlock(
                    text="It has two sentences.", kind=block.kind, location=block.location
                )
            else:
                yield block


@requires_database
async def test_new_version_keeps_codes_of_unchanged_blocks(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Критерий процесса: неизменившиеся блоки сохраняют коды, прежние коды не переиспользуются."""
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)
    first = await extract(db_client, account, chapters[0]["id"])
    before = await blocks_of(db_client, account, first["id"])

    monkeypatch.setattr(masters_module, "parser_for", lambda _format: _FixedParser())
    second = await extract(
        db_client, account, chapters[0]["id"], reason="Разборщик терял запятую в первом абзаце"
    )
    after = await blocks_of(db_client, account, second["id"])

    assert second["version"] == 2
    assert second["supersedes_id"] == first["id"]

    codes = {block["source_text"]: block["full_code"] for block in after}
    # Заголовок и листинг не менялись — коды те же.
    assert codes["1 Introduction"] == "CH01-B0001"
    assert codes["def entropy(p):\n    return -sum(p * log(p))"] == "CH01-B0004"
    # Изменённый и разделённый — новые коды со ссылкой на предка.
    corrected = next(block for block in after if block["source_text"].startswith("First"))
    assert corrected["full_code"] == "CH01-B0005"
    assert corrected["parent_code"] == "CH01-B0002"
    halves = [block for block in after if block["parent_code"] == "CH01-B0003"]
    assert [block["source_text"] for block in halves] == [
        "Second paragraph.",
        "It has two sentences.",
    ]

    # Первая версия осталась такой, какой была: те же блоки, тот же текст.
    still = await blocks_of(db_client, account, first["id"])
    assert still == [{**block, "active": still[i]["active"]} for i, block in enumerate(before)]
    assert [block["active"] for block in still] == [True, False, False, True]
    # Неизменность проверяема, а не объявлена: сумма первой версии
    # пересчитывается по её блокам и объектам и после появления второй.
    objects = await db_client.get(f"/masters/{first['id']}/objects", headers=account.headers)
    places = {block["full_code"]: index for index, block in enumerate(still)}
    recomputed = master_checksum(
        [(BlockKind(block["kind"]), block["source_text"]) for block in still],
        [
            PlacedEntry(
                type=ObjectType(item["type"]),
                checksum=item["checksum"],
                at=item["at"],
                content=tuple(places[code] for code in item["content_codes"]),
                caption=places[item["caption_code"]] if item["caption_code"] else None,
            )
            for item in objects.json()
        ],
    )
    assert recomputed == first["checksum"]


@requires_database
async def test_retired_block_is_still_found_by_code(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    book_id, chapters = await approved_book(db_client, account)
    await extract(db_client, account, chapters[0]["id"])
    monkeypatch.setattr(masters_module, "parser_for", lambda _format: _FixedParser())
    await extract(db_client, account, chapters[0]["id"], reason="Разборщик терял запятую")

    found = await db_client.get(f"/books/{book_id}/blocks/ch01-b0002", headers=account.headers)

    assert found.status_code == 200, found.text
    assert found.json()["block"]["active"] is False
    # В текущей версии его нет — места у него нет, но и «не найдено» он не стал.
    assert found.json()["position"] is None


@requires_database
async def test_block_is_found_by_code_anywhere(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book_id, chapters = await approved_book(db_client, account)
    await extract(db_client, account, chapters[1]["id"])

    in_book = await db_client.get(f"/books/{book_id}/blocks/CH02-B0002", headers=account.headers)
    assert in_book.status_code == 200, in_book.text
    assert in_book.json()["block"]["source_text"] == "Noise."
    assert in_book.json()["position"] == 1

    everywhere = await db_client.get(
        "/blocks/lookup", params={"code": "BK01-CH02-B0002"}, headers=account.headers
    )
    assert everywhere.status_code == 200, everywhere.text
    assert everywhere.json()["book_id"] == book_id

    malformed = await db_client.get(
        "/blocks/lookup", params={"code": "chapter two"}, headers=account.headers
    )
    assert malformed.status_code == 400

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")
    hidden = await db_client.get(
        "/blocks/lookup", params={"code": "BK01-CH02-B0002"}, headers=stranger.headers
    )
    assert hidden.status_code == 404


@requires_database
async def test_only_current_version_is_approved(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)
    first = await extract(db_client, account, chapters[0]["id"])
    monkeypatch.setattr(masters_module, "parser_for", lambda _format: _FixedParser())
    second = await extract(db_client, account, chapters[0]["id"], reason="Разборщик терял запятую")

    stale = await db_client.post(f"/masters/{first['id']}/approval", headers=account.headers)
    assert stale.status_code == 409

    current = await db_client.post(f"/masters/{second['id']}/approval", headers=account.headers)
    assert current.status_code == 200, current.text
    assert current.json()["approved_at"] is not None


@requires_database
async def test_chapter_with_master_keeps_its_boundaries(db_client: AsyncClient) -> None:
    """Перенос блока в другую главу сменил бы его код — границы такой главы не двигаются."""
    account = await register(db_client)
    _, chapters = await approved_book(db_client, account)
    await extract(db_client, account, chapters[0]["id"])

    merged = await db_client.post(f"/chapters/{chapters[0]['id']}/merge", headers=account.headers)

    assert merged.status_code == 409
    assert "мастер" in merged.json()["detail"]


@requires_database
async def test_viewer_cannot_extract(db_client: AsyncClient, session: AsyncSession) -> None:
    owner = await register(db_client)
    _, chapters = await approved_book(db_client, owner)
    guest = await register(db_client, email="guest@example.com", organization_name="Своя")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    response = await db_client.post(
        f"/chapters/{chapters[0]['id']}/masters",
        headers=guest.headers_for(owner.organization_id),
        json={},
    )

    assert response.status_code == 403


def test_block_kind_values_are_stable() -> None:
    """Вид блока хранится в базе по имени — переименование значений сломало бы данные."""
    assert [kind.name for kind in BlockKind] == [
        "PARAGRAPH",
        "HEADING",
        "LIST_ITEM",
        "TABLE_CELL",
        "CAPTION",
        "WARNING",
        "CODE",
    ]
