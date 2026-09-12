"""Память переводов через API.

Проверяется то, ради чего у памяти есть экран: видно, какие пары
пригодились и сколько раз; правка человека вытесняет машинный вариант и
попадает в следующую книгу; снятая пара в перевод больше не идёт.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import register
from tests.test_translation import MANUAL, prepare


async def translated_book(client: AsyncClient, account, *, data: bytes = MANUAL) -> str:
    document_id = await prepare(client, account, data=data)

    response = await client.post(f"/documents/{document_id}/translate", headers=account.headers)
    assert response.status_code == 200, response.text

    return document_id


@requires_database
async def test_memory_shows_pairs_and_how_often_they_helped(db_client: AsyncClient) -> None:
    account = await register(db_client)

    await translated_book(db_client, account)
    await translated_book(db_client, account, data=MANUAL + b"\nOne more paragraph.\n")

    response = await db_client.get("/memory", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()

    # Три разных текста первой книги и один новый из второй.
    assert body["total"] == 4
    # Вторая книга закрыла памятью три разных текста — столько раз пары и
    # пригодились: повтор внутри книги считается один раз, он и в модель
    # ушёл бы один раз. Пригодившиеся впереди, новая пара из второй книги
    # — в конце, у неё ноль.
    assert body["summary"]["hits"] == 3
    assert [item["hits"] for item in body["items"]] == [1, 1, 1, 0]
    assert body["items"][-1]["source_text"] == "One more paragraph."
    assert body["summary"]["saved_characters"] > 0
    # Заглушка не в прейскуранте — деньги честно не считаются.
    assert body["summary"]["saved_usd"] is None


@requires_database
async def test_memory_search_and_origin_filter(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await translated_book(db_client, account)

    found = await db_client.get("/memory", headers=account.headers, params={"query": "gauge"})

    assert [item["source_text"] for item in found.json()["items"]] == ["Check the pressure gauge."]

    human = await db_client.get("/memory", headers=account.headers, params={"origin": "human"})

    assert human.json()["total"] == 0
    assert human.json()["summary"]["units"] == 3


@requires_database
async def test_human_edit_wins_in_the_next_book(db_client: AsyncClient) -> None:
    """Правка редактора надёжнее следующей модели — и она уходит дальше."""
    account = await register(db_client)
    await translated_book(db_client, account)

    listing = (await db_client.get("/memory", headers=account.headers)).json()
    unit = next(item for item in listing["items"] if item["source_text"].startswith("Check"))

    edited = await db_client.patch(
        f"/memory/{unit['id']}",
        headers=account.headers,
        json={"target_text": "Проверьте манометр."},
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["origin"] == "human"

    second = await translated_book(db_client, account)
    segments = (
        await db_client.get(f"/documents/{second}/segments", headers=account.headers)
    ).json()["items"]

    assert segments[2]["target_text"] == "Проверьте манометр."
    assert (await db_client.get("/memory", headers=account.headers)).json()["summary"][
        "human_units"
    ] == 1


@requires_database
async def test_removed_pair_goes_to_the_model_again(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await translated_book(db_client, account)

    listing = (await db_client.get("/memory", headers=account.headers)).json()
    unit = next(item for item in listing["items"] if item["source_text"].startswith("Open"))

    removed = await db_client.delete(f"/memory/{unit['id']}", headers=account.headers)
    assert removed.status_code == 204

    second = await prepare(db_client, account)
    body = (await db_client.post(f"/documents/{second}/translate", headers=account.headers)).json()

    # Из четырёх сегментов один ушёл в модель заново, остальные — из памяти.
    assert body["from_provider"] == 1
    assert body["from_memory"] == 3


@requires_database
async def test_memory_is_scoped_to_organization(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await translated_book(db_client, account)

    unit_id = (await db_client.get("/memory", headers=account.headers)).json()["items"][0]["id"]
    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    listing = (await db_client.get("/memory", headers=stranger.headers)).json()

    assert listing["total"] == 0
    assert listing["summary"]["units"] == 0
    assert (
        await db_client.delete(f"/memory/{unit_id}", headers=stranger.headers)
    ).status_code == 404
