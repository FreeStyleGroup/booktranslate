"""Контекст при переводе и проверки на выходе — через API.

Модульные тесты проверяют сами правила; здесь проверяется, что до модели
доезжает то, что задумано, а находки доезжают до сегмента.
"""

from httpx import AsyncClient

from app.services.providers import TranslationRequest
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

MANUAL = (
    b"# Safety\n"
    b"\n"
    b"Disconnect the power supply.\n"
    b"\n"
    b"Wait until the indicator goes off.\n"
    b"\n"
    b"Open the housing.\n"
)


async def prepare(client: AsyncClient, account: Account, *, data: bytes, name: str) -> str:
    project_id = await create_project(client, account)

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": (name, data, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id: str = uploaded.json()["id"]

    parsed = await client.post(f"/documents/{document_id}/parse", headers=account.headers)
    assert parsed.status_code == 200, parsed.text

    return document_id


async def segments(client: AsyncClient, account: Account, document_id: str) -> list[dict]:
    response = await client.get(f"/documents/{document_id}/segments", headers=account.headers)
    items: list[dict] = response.json()["items"]

    return items


@requires_database
async def test_context_reaches_the_model(
    db_client: AsyncClient, provider_log: list[TranslationRequest]
) -> None:
    """Без соседей «указанный выше» и местоимения переводятся наугад."""
    account = await register(db_client)
    document_id = await prepare(db_client, account, data=MANUAL, name="manual.md")

    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    middle = next(
        request
        for request in provider_log
        if request.source_text == "Wait until the indicator goes off."
    )

    assert "Disconnect the power supply." in middle.context.before
    assert middle.context.after == ("Open the housing.",)
    # Заголовок задаёт предметную область на десятки сегментов вперёд.
    assert middle.context.heading == "Safety"


@requires_database
async def test_heading_does_not_precede_itself(
    db_client: AsyncClient, provider_log: list[TranslationRequest]
) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account, data=MANUAL, name="manual.md")

    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    heading = next(request for request in provider_log if request.source_text == "Safety")

    assert heading.context.heading is None


@requires_database
async def test_terms_reach_the_model(
    db_client: AsyncClient, provider_log: list[TranslationRequest]
) -> None:
    """Термин уходит в запрос как ограничение — иначе словарь ни на что не влияет."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "housing",
            "target_term": "корпус",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    document_id = await prepare(db_client, account, data=MANUAL, name="manual.md")
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    request = next(item for item in provider_log if item.source_text == "Open the housing.")

    assert [term.target for term in request.terms] == ["корпус"]


@requires_database
async def test_first_use_expansion_is_required_once(db_client: AsyncClient) -> None:
    """«маркет-мейкер (market maker, MM)» — при первом употреблении, дальше просто MM."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "MM",
            "target_term": "маркет-мейкер",
            "source_language": "en",
            "target_language": "ru",
            "kind": "abbreviation",
            "expand_on_first_use": True,
        },
    )

    document_id = await prepare(
        db_client,
        account,
        data=b"The MM quotes prices.\n\nThe MM holds inventory.\n",
        name="book.txt",
    )
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    items = await segments(db_client, account, document_id)

    # Заглушка подставила перевод вместо сокращения, и в первом употреблении
    # самого сокращения не осталось — это и есть находка.
    assert items[0]["status"] == "flagged"
    assert [finding["check"] for finding in items[0]["quality"]["findings"]] == ["first_use"]

    # Второе употребление раскрывать не нужно: требование относится к первому.
    assert items[1]["quality"] is None


@requires_database
async def test_clean_segment_keeps_no_verdict(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account, data=MANUAL, name="manual.md")

    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    items = await segments(db_client, account, document_id)

    assert all(item["quality"] is None for item in items)
    assert all(item["quality_score"] is None for item in items)


@requires_database
async def test_finding_lands_in_the_segment_with_a_score(db_client: AsyncClient) -> None:
    """Оценка нужна не сама по себе, а чтобы редактор начинал с худшего."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            # Регистр не совпадает с текстом: сопоставление термин найдёт, а
            # заглушка подставить не сможет.
            "source_term": "Power Supply",
            "target_term": "источник питания",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    document_id = await prepare(db_client, account, data=MANUAL, name="manual.md")
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    items = await segments(db_client, account, document_id)
    flagged = next(item for item in items if item["status"] == "flagged")

    assert flagged["quality"]["findings"][0]["check"] == "glossary"
    assert "источник питания" in flagged["quality"]["findings"][0]["message"]
    assert 0.0 < flagged["quality_score"] < 1.0
