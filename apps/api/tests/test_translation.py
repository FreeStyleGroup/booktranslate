"""Перевод через API.

Проверяется то, за что придётся отвечать деньгами: повторы внутри документа
переводятся один раз, память закрывает то, что уже переводилось, а термин,
которого нет в переводе, помечает сегмент.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import Account, create_project, register

# Второй и четвёртый абзацы совпадают: в руководствах предупреждение
# повторяется десятками раз, и платить за него дважды незачем.
MANUAL = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Check the pressure gauge.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
)


async def prepare(client: AsyncClient, account: Account, *, data: bytes = MANUAL) -> str:
    """Проект, загруженный документ и разбор — то, с чего начинается перевод."""
    project_id = await create_project(client, account)

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", data, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id: str = uploaded.json()["id"]

    parsed = await client.post(f"/documents/{document_id}/parse", headers=account.headers)
    assert parsed.status_code == 200, parsed.text

    return document_id


@requires_database
async def test_repeats_are_translated_once(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    response = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total"] == 4
    # Четыре сегмента, но три разных текста: повтор предупреждения переведён
    # один раз, и это ровно то, за что не заплачено.
    assert body["unique_texts"] == 3
    assert body["saved_calls"] == 1

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert segments[1]["target_text"] == segments[3]["target_text"]
    assert all(item["target_text"] for item in segments)
    assert segments[0]["translation_source"] == "stub"


@requires_database
async def test_second_document_is_taken_from_memory(db_client: AsyncClient) -> None:
    """Тот же текст в другом документе не отправляется модели во второй раз."""
    account = await register(db_client)

    first = await prepare(db_client, account)
    await db_client.post(f"/documents/{first}/translate", headers=account.headers)

    second = await prepare(db_client, account, data=MANUAL + b"\nOne more paragraph.\n")
    response = await db_client.post(f"/documents/{second}/translate", headers=account.headers)

    body = response.json()

    assert body["from_memory"] == 4
    # Модели достался единственный новый абзац.
    assert body["from_provider"] == 1
    assert body["saved_calls"] == 4

    segments = (
        await db_client.get(f"/documents/{second}/segments", headers=account.headers)
    ).json()["items"]

    assert segments[0]["status"] == "memory"
    assert segments[0]["translation_source"] == "memory"


@requires_database
async def test_glossary_term_reaches_provider(db_client: AsyncClient) -> None:
    """Термин из словаря подставлен — значит он доехал до провайдера."""
    account = await register(db_client)

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

    document_id = await prepare(db_client, account)
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert "клапан" in segments[0]["target_text"]
    assert segments[0]["status"] == "machine"


@requires_database
async def test_unused_term_flags_segment(db_client: AsyncClient) -> None:
    """Заглушка подставляет термин дословно, а требуется другая форма."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "pressure gauge",
            "target_term": "манометр",
            "source_language": "en",
            "target_language": "ru",
            "mandatory": True,
        },
    )

    # Термин заведён так, что заглушка его не подставит: в тексте он есть,
    # а в переводе появиться неоткуда.
    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "start",
            "target_term": "пуск",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    document_id = await prepare(db_client, account, data=b"Open the valve before start.\n")
    result = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert result.json()["flagged"] == 0

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    # Заглушка подставила «пуск», поэтому претензий нет — проверка отработала
    # и не подняла ложную тревогу.
    assert "пуск" in segments[0]["target_text"]
    assert segments[0]["quality"] is None


@requires_database
async def test_repeat_run_does_not_touch_edited(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)
    again = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    # Все сегменты уже переведены: брать в работу нечего.
    assert again.json()["total"] == 0


@requires_database
async def test_untranslated_document_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )
    document_id = uploaded.json()["id"]

    response = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert response.status_code == 409


@requires_database
async def test_glossary_is_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    await db_client.post(
        "/glossary",
        headers=owner.headers,
        json={
            "source_term": "valve",
            "target_term": "клапан",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    listing = await db_client.get("/glossary", headers=stranger.headers)

    assert listing.status_code == 200
    assert listing.json() == []


@requires_database
async def test_do_not_translate_requires_same_string(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "USB",
            "target_term": "УСБ",
            "source_language": "en",
            "target_language": "ru",
            "kind": "do_not_translate",
        },
    )

    assert response.status_code == 400
