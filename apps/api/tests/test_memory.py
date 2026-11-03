"""Память переводов через API.

Проверяется то, ради чего у памяти есть экран: видно, какие пары есть, пригодились ли и
сколько раз; правка человека вытесняет машинный вариант и попадает в следующую книгу;
снятая пара в перевод больше не идёт.

Черновики в память сами не попадают: публикация придёт вместе с проверкой исправлений.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Role, User
from app.services.context import RequestContext
from app.services.memory import TranslationMemory
from tests.chapters import block_rows, open_book, translate
from tests.conftest import requires_database
from tests.factories import Account, register

MANUAL = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Check the pressure gauge every day.\n"
)

PAIRS = [
    ("Open the valve before start.", "Откройте клапан перед пуском."),
    ("Warning! Disconnect the power supply.", "Внимание! Отключите питание."),
    ("Check the pressure gauge every day.", "Проверяйте манометр каждый день."),
]


async def seed(session: AsyncSession, account: Account, pairs: list[tuple[str, str]]) -> None:
    user = await session.get(User, account.user_id)
    assert user is not None
    context = RequestContext(user=user, organization_id=account.organization_id, role=Role.OWNER)

    await TranslationMemory(session, context).remember(
        pairs, source_language="en", target_language="ru", origin="claude-opus-5", verified=True
    )
    await session.commit()


@requires_database
async def test_memory_shows_pairs_and_how_often_they_helped(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    await seed(session, account, [*PAIRS, ("One more paragraph.", "Ещё один абзац.")])

    book = await open_book(db_client, account, data=MANUAL)
    state = await translate(db_client, session, account, book.chapter)

    assert state["latest"]["from_memory"] == 3
    assert state["latest"]["from_model"] == 0

    body = (await db_client.get("/memory", headers=account.headers)).json()

    assert body["total"] == 4
    assert body["summary"]["hits"] == 3
    assert [item["hits"] for item in body["items"]] == [1, 1, 1, 0]
    assert body["items"][-1]["source_text"] == "One more paragraph."
    assert body["summary"]["saved_characters"] > 0
    # Заглушка не в прейскуранте — деньги честно не считаются.
    assert body["summary"]["saved_usd"] is None


@requires_database
async def test_draft_translation_does_not_enter_the_memory(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Память пополняется проверенным, а не черновиком: иначе ошибка размножится."""
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)

    await translate(db_client, session, account, book.chapter)

    assert (await db_client.get("/memory", headers=account.headers)).json()["total"] == 0


@requires_database
async def test_memory_search_and_origin_filter(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    await seed(session, account, PAIRS)

    found = await db_client.get("/memory", headers=account.headers, params={"query": "gauge"})

    assert [item["source_text"] for item in found.json()["items"]] == [PAIRS[2][0]]

    human = await db_client.get("/memory", headers=account.headers, params={"origin": "human"})

    assert human.json()["total"] == 0
    assert human.json()["summary"]["units"] == 3


@requires_database
async def test_human_edit_wins_in_the_next_book(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    await seed(session, account, PAIRS)

    listing = (await db_client.get("/memory", headers=account.headers)).json()
    unit = next(item for item in listing["items"] if item["source_text"].startswith("Check"))

    edited = await db_client.patch(
        f"/memory/{unit['id']}",
        headers=account.headers,
        json={"target_text": "Проверьте манометр."},
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["origin"] == "human"

    book = await open_book(db_client, account, data=MANUAL)
    await translate(db_client, session, account, book.chapter)

    rows = await block_rows(db_client, account, book.chapter)
    row = next(item for item in rows if item["source_text"].startswith("Check"))

    assert row["current"]["text"] == "Проверьте манометр."
    assert row["current"]["origin"] == "memory"

    history = await db_client.get(f"/blocks/{row['id']}/revisions", headers=account.headers)
    assert uuid.UUID(history.json()["items"][0]["memory_unit_id"]) == uuid.UUID(unit["id"])

    summary = (await db_client.get("/memory", headers=account.headers)).json()["summary"]
    assert summary["human_units"] == 1


@requires_database
async def test_removed_pair_goes_to_the_model_again(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    await seed(session, account, PAIRS)

    listing = (await db_client.get("/memory", headers=account.headers)).json()
    unit = next(item for item in listing["items"] if item["source_text"].startswith("Open"))

    removed = await db_client.delete(f"/memory/{unit['id']}", headers=account.headers)
    assert removed.status_code == 204

    book = await open_book(db_client, account, data=MANUAL)
    state = await translate(db_client, session, account, book.chapter)

    assert state["latest"]["from_model"] == 1
    assert state["latest"]["from_memory"] == 2


@requires_database
async def test_memory_is_scoped_to_organization(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    await seed(session, account, PAIRS)

    unit_id = (await db_client.get("/memory", headers=account.headers)).json()["items"][0]["id"]
    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    listing = (await db_client.get("/memory", headers=stranger.headers)).json()

    assert listing["total"] == 0
    assert listing["summary"]["units"] == 0
    assert (
        await db_client.delete(f"/memory/{unit_id}", headers=stranger.headers)
    ).status_code == 404
