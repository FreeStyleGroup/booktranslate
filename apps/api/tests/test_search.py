"""Общий поиск через API.

Проверяется главное: одно слово находится во всех четырёх местах, где оно
может лежать, чужое пространство не видно, а поиск по одной букве не
принимается.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import register
from tests.test_catalog import lookup
from tests.test_translation import MANUAL, prepare


@requires_database
async def test_one_word_is_found_everywhere(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

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

    # Книга называется «manual» — по слову «valve» её нет, и это верно.
    assert body["documents"]["total"] == 0
    assert [item["source_term"] for item in body["terms"]["items"]] == ["valve"]
    assert [item["source_term"] for item in body["entries"]["items"]] == ["check valve"]
    assert body["segments"]["total"] == 1
    hit = body["segments"]["items"][0]
    assert hit["source_text"] == "Open the valve before start."
    assert hit["document_title"] == "manual"
    assert hit["document_id"] == document_id
    assert hit["position"] == 0


@requires_database
async def test_search_counts_beyond_the_shown(db_client: AsyncClient) -> None:
    """Число считается по всей базе, показывается несколько: видно, куда идти."""
    account = await register(db_client)
    document_id = await prepare(db_client, account, data=MANUAL)

    response = await db_client.get(
        "/search", headers=account.headers, params={"query": "the", "limit": 1}
    )
    body = response.json()

    assert body["documents"]["total"] == 0
    # Слово «the» есть во всех четырёх сегментах; показан один.
    assert body["segments"]["total"] == 4
    assert len(body["segments"]["items"]) == 1
    assert body["segments"]["items"][0]["document_id"] == document_id


@requires_database
async def test_search_finds_books_by_title_and_stays_in_the_organization(
    db_client: AsyncClient,
) -> None:
    account = await register(db_client)
    await prepare(db_client, account)

    mine = await db_client.get("/search", headers=account.headers, params={"query": "manu"})
    assert mine.json()["documents"]["total"] == 1

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    theirs = await db_client.get("/search", headers=stranger.headers, params={"query": "manu"})

    assert theirs.status_code == 200
    assert theirs.json()["documents"]["total"] == 0
    assert theirs.json()["segments"]["total"] == 0


@requires_database
async def test_search_rejects_a_single_letter(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.get("/search", headers=account.headers, params={"query": "v"})

    assert response.status_code == 422
