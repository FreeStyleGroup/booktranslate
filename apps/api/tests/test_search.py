"""Общий поиск через API.

Проверяется главное: одно слово находится во всех местах, где оно может лежать, чужое
пространство не видно, а поиск по одной букве не принимается.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.chapters import open_book, translated_book
from tests.conftest import requires_database
from tests.factories import register
from tests.test_catalog import lookup

MANUAL = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Check the pressure gauge.\n"
    b"\n"
    b"Close the door.\n"
)


@requires_database
async def test_one_word_is_found_everywhere(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    book = await translated_book(db_client, session, account, data=MANUAL)

    added = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "valve",
            "target_term": "клапан",
            "source_language": "en",
            "target_language": "ru",
        },
    )
    assert added.status_code == 201, added.text
    await lookup(db_client, account, ["check valve"])

    response = await db_client.get("/search", headers=account.headers, params={"query": "VALVE"})

    assert response.status_code == 200, response.text
    body = response.json()

    # Файл называется «manual» — по слову «valve» его нет, и это правильно.
    assert body["documents"]["total"] == 0
    assert [item["source_term"] for item in body["terms"]["items"]] == ["valve"]
    assert [item["source_term"] for item in body["entries"]["items"]] == ["check valve"]
    assert body["blocks"]["total"] == 1
    hit = body["blocks"]["items"][0]
    assert hit["source_text"] == "Open the valve before start."
    assert hit["translation"] == "[ru] Open the valve before start."
    assert hit["book_title"] == "Manual"
    assert hit["book_id"] == book.book_id
    assert hit["chapter_id"] == book.chapter
    assert hit["full_code"].startswith("CH01-B")


@requires_database
async def test_translation_is_searched_too(db_client: AsyncClient, session: AsyncSession) -> None:
    """Редактор ищет фразу так, как она написана в переводе."""
    account = await register(db_client)
    await translated_book(db_client, session, account, data=MANUAL)

    response = await db_client.get(
        "/search", headers=account.headers, params={"query": "[ru] Open"}
    )

    assert response.json()["blocks"]["total"] == 1


@requires_database
async def test_search_counts_beyond_the_shown(db_client: AsyncClient) -> None:
    """Число считается по всей базе, показывается несколько."""
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)

    response = await db_client.get(
        "/search", headers=account.headers, params={"query": "the", "limit": 1}
    )
    body = response.json()

    assert body["documents"]["total"] == 0
    # Слово «the» есть во всех четырёх блоках; показан один.
    assert body["blocks"]["total"] == 4
    assert len(body["blocks"]["items"]) == 1
    assert body["blocks"]["items"][0]["book_id"] == book.book_id


@requires_database
async def test_search_finds_files_and_stays_in_the_organization(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await open_book(db_client, account, data=MANUAL)

    mine = await db_client.get("/search", headers=account.headers, params={"query": "manu"})
    assert mine.json()["documents"]["total"] == 1

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    theirs = await db_client.get("/search", headers=stranger.headers, params={"query": "manu"})

    assert theirs.status_code == 200
    assert theirs.json()["documents"]["total"] == 0
    assert theirs.json()["blocks"]["total"] == 0


@requires_database
async def test_search_rejects_a_single_letter(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.get("/search", headers=account.headers, params={"query": "v"})

    assert response.status_code == 422
