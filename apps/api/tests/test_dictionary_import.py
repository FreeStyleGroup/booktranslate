"""Загрузка словаря через API.

Главное здесь — не то, что записи доехали, а то, что загруженное не затирает
ручную работу: потерянная правка редактора обнаруживается через месяц, на
готовом переводе.
"""

from typing import Any

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import Account, register

GLOSSARY = "source,target,note\nvalve,клапан,\npump,насос,\n".encode()


async def upload(
    client: AsyncClient,
    account: Account,
    *,
    data: bytes = GLOSSARY,
    name: str = "glossary.csv",
    **form: str,
) -> dict[str, Any]:
    response = await client.post(
        "/glossary/import",
        headers=account.headers,
        files={"file": (name, data, "text/csv")},
        data={"source_language": "en", "target_language": "ru", **form},
    )

    body: dict[str, Any] = response.json()
    body["_status"] = response.status_code

    return body


async def add_manual(client: AsyncClient, account: Account, target: str) -> None:
    response = await client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "valve",
            "target_term": target,
            "source_language": "en",
            "target_language": "ru",
        },
    )
    assert response.status_code == 201, response.text


@requires_database
async def test_import_fills_glossary(db_client: AsyncClient) -> None:
    account = await register(db_client)

    report = await upload(db_client, account, origin="Заказчик")

    assert report["_status"] == 200, report
    assert (report["added"], report["updated"], report["skipped"]) == (2, 0, 0)

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    terms = {item["source_term"]: item for item in glossary}

    assert terms["valve"]["target_term"] == "клапан"
    # По метке видно, что запись загружена, а не заведена руками: иначе
    # пачку не обновить и не снять, не задев чужую работу.
    assert terms["valve"]["source"] == "import:Заказчик"
    # Чужой словарь верен не весь — он предложен, а не подтверждён.
    assert terms["valve"]["status"] == "proposed"


@requires_database
async def test_import_does_not_overwrite_manual(db_client: AsyncClient) -> None:
    """Человек, правивший термин, знает про книгу больше, чем чужая база."""
    account = await register(db_client)
    await add_manual(db_client, account, "вентиль")

    report = await upload(db_client, account)

    assert (report["added"], report["skipped"]) == (1, 1)
    assert any("заведён вручную" in reason for reason in report["reasons"])

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    terms = {item["source_term"]: item for item in glossary}

    assert terms["valve"]["target_term"] == "вентиль"
    assert terms["valve"]["status"] == "confirmed"


@requires_database
async def test_import_overwrites_manual_when_asked(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await add_manual(db_client, account, "вентиль")

    report = await upload(db_client, account, overwrite_manual="true")

    assert (report["added"], report["updated"], report["skipped"]) == (1, 1, 0)

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    terms = {item["source_term"]: item for item in glossary}

    assert terms["valve"]["target_term"] == "клапан"


@requires_database
async def test_second_import_updates_rather_than_duplicates(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await upload(db_client, account)

    report = await upload(db_client, account, data="source,target\nvalve,затвор\n".encode())

    assert (report["added"], report["updated"]) == (0, 1)

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()

    assert len(glossary) == 2
    assert next(item for item in glossary if item["source_term"] == "valve")["target_term"] == (
        "затвор"
    )


@requires_database
async def test_repeated_row_inside_file_does_not_break_import(db_client: AsyncClient) -> None:
    """Повтор в файле — уточнение ниже по списку, а не повод не загрузить ничего."""
    account = await register(db_client)

    report = await upload(
        db_client, account, data="source,target\nvalve,клапан\nvalve,затвор\n".encode()
    )

    assert report["_status"] == 200, report
    assert report["added"] == 1

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()

    assert glossary[0]["target_term"] == "затвор"


@requires_database
async def test_imported_terms_reach_translation(db_client: AsyncClient) -> None:
    """Загруженное сразу работает: термин уходит модели и подставляется."""
    account = await register(db_client)
    await upload(db_client, account)

    project = await db_client.post(
        "/projects",
        headers=account.headers,
        json={"name": "Книга", "source_language": "en", "target_language": "ru"},
    )
    project_id = project.json()["id"]

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", b"Open the valve.\n", "text/plain")},
    )
    document_id = uploaded.json()["id"]

    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert "клапан" in segments[0]["target_text"]


@requires_database
async def test_unknown_format_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)

    report = await upload(db_client, account, name="glossary.pdf")

    assert report["_status"] == 400
    assert "формат" in report["detail"].casefold()


@requires_database
async def test_import_is_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    await upload(db_client, owner)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    listing = await db_client.get("/glossary", headers=stranger.headers)

    assert listing.json() == []
