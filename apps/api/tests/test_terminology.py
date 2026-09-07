"""Терминологический проход через API.

Проверяется то, ради чего он существует: словарь книги решается до перевода,
решение переживает повторный проход, а неустоявшийся термин не выдаётся за
ошибку перевода.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import Account, create_project, register

# Сочетание повторяется трижды — ровно то, что должно попасть в словарь.
# Обозначение стандарта встречается один раз: его в перевод переносят как
# есть независимо от частоты.
MANUAL = (
    b"Open the check valve before start.\n"
    b"\n"
    b"The check valve must be closed.\n"
    b"\n"
    b"Inspect the check valve every month. Complies with ISO 9001.\n"
)


async def prepare(client: AsyncClient, account: Account, *, data: bytes = MANUAL) -> str:
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


async def extract(client: AsyncClient, account: Account, document_id: str) -> list[dict]:
    response = await client.post(
        f"/documents/{document_id}/terminology/extract", headers=account.headers
    )
    assert response.status_code == 200, response.text

    items: list[dict] = response.json()
    return items


def by_source(candidates: list[dict], source: str) -> dict:
    match = [item for item in candidates if item["source_term"].casefold() == source.casefold()]
    assert match, f"{source} не найден среди {[item['source_term'] for item in candidates]}"

    return match[0]


@requires_database
async def test_extract_collects_candidates(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    candidates = await extract(db_client, account, document_id)

    valve = by_source(candidates, "check valve")

    assert valve["status"] == "new"
    assert valve["frequency"] == 3
    assert valve["kind"] == "term"
    # Первое вхождение — в самом первом сегменте: по нему возвращаются к
    # тексту, когда спорят о термине.
    assert valve["first_position"] == 0
    assert "check valve" in valve["sample"]

    assert by_source(candidates, "ISO 9001")["kind"] == "do_not_translate"


@requires_database
async def test_translation_waits_for_decisions(db_client: AsyncClient) -> None:
    """Перевод поверх нерешённого словаря — ровно та ошибка, ради которой всё это."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await extract(db_client, account, document_id)

    response = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert response.status_code == 409
    assert "Терминологический проход" in response.json()["detail"]


@requires_database
async def test_ignore_terminology_lets_translation_through(db_client: AsyncClient) -> None:
    """Обойти проверку можно, но осознанно — умолчание остаётся строгим."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await extract(db_client, account, document_id)

    response = await db_client.post(
        f"/documents/{document_id}/translate?ignore_terminology=true", headers=account.headers
    )

    assert response.status_code == 200, response.text


@requires_database
async def test_accepted_term_reaches_translation(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    candidates = await extract(db_client, account, document_id)

    decisions = [
        {
            "candidate_id": by_source(candidates, "check valve")["id"],
            "accept": True,
            "target_term": "обратный клапан",
        },
        # Непереводимому перевод не нужен: он совпадает с исходником.
        {"candidate_id": by_source(candidates, "ISO 9001")["id"], "accept": True},
    ]

    report = await db_client.post(
        f"/documents/{document_id}/terminology/decisions",
        headers=account.headers,
        json={"decisions": decisions},
    )
    assert report.status_code == 200, report.text
    assert report.json() == {"accepted": 2, "rejected": 0, "remaining": 0}

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    terms = {item["source_term"]: item for item in glossary}

    assert terms["check valve"]["source"] == "extracted"
    assert terms["check valve"]["status"] == "confirmed"
    # У непереводимого перевод подставлен сам, копировать строку руками не
    # пришлось.
    assert terms["ISO 9001"]["target_term"] == "ISO 9001"

    translated = await db_client.post(
        f"/documents/{document_id}/translate", headers=account.headers
    )
    assert translated.status_code == 200, translated.text

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert "обратный клапан" in segments[0]["target_text"]


@requires_database
async def test_abbreviation_keeps_expansion_in_note(db_client: AsyncClient) -> None:
    """Расшифровка из текста уезжает в примечание к термину, а не теряется."""
    account = await register(db_client)
    document_id = await prepare(
        db_client,
        account,
        data=(
            b"The Programmable Logic Controller (PLC) runs the cycle.\n\nReplace the PLC module.\n"
        ),
    )

    candidates = await extract(db_client, account, document_id)
    plc = by_source(candidates, "PLC")

    assert plc["kind"] == "abbreviation"
    assert plc["expansion"] == "Programmable Logic Controller"

    await db_client.post(
        f"/documents/{document_id}/terminology/decisions",
        headers=account.headers,
        json={"decisions": [{"candidate_id": plc["id"], "accept": True, "target_term": "ПЛК"}]},
    )

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    term = next(item for item in glossary if item["source_term"] == "PLC")

    assert term["note"] == "Programmable Logic Controller"
    # Аббревиатуру при первом употреблении принято раскрывать — это правило
    # технического текста, и по умолчанию оно включено.
    assert term["expand_on_first_use"] is True


@requires_database
async def test_rejected_candidate_does_not_come_back(db_client: AsyncClient) -> None:
    """Иначе на повторном проходе редактор увидит те же строки заново."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    candidates = await extract(db_client, account, document_id)

    await db_client.post(
        f"/documents/{document_id}/terminology/decisions",
        headers=account.headers,
        json={
            "decisions": [
                {"candidate_id": by_source(candidates, "check valve")["id"], "accept": False}
            ]
        },
    )

    again = await extract(db_client, account, document_id)

    assert by_source(again, "check valve")["status"] == "rejected"


@requires_database
async def test_settled_term_flags_missing_translation(db_client: AsyncClient) -> None:
    """Подтверждённый обязательный термин, которого нет в переводе, — это ошибка."""
    account = await register(db_client)

    # Регистр не совпадает с текстом: сопоставление термин найдёт, а заглушка
    # подставить не сможет — так получается перевод без нужного слова.
    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "Check Valve",
            "target_term": "обратный клапан",
            "source_language": "en",
            "target_language": "ru",
            "status": "confirmed",
        },
    )

    document_id = await prepare(db_client, account)
    result = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert result.json()["flagged"] == 3

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert segments[0]["status"] == "flagged"


@requires_database
async def test_unsettled_term_does_not_flag(db_client: AsyncClient) -> None:
    """Спор о словаре не должен выглядеть как сотня ошибок перевода."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "Check Valve",
            "target_term": "обратный клапан",
            "source_language": "en",
            "target_language": "ru",
            "status": "needs_unification",
        },
    )

    document_id = await prepare(db_client, account)
    result = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert result.json()["flagged"] == 0


@requires_database
async def test_retired_term_is_ignored(db_client: AsyncClient) -> None:
    account = await register(db_client)

    added = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "Check Valve",
            "target_term": "обратный клапан",
            "source_language": "en",
            "target_language": "ru",
        },
    )
    term_id = added.json()["id"]

    retired = await db_client.patch(
        f"/glossary/{term_id}", headers=account.headers, json={"status": "retired"}
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "retired"

    document_id = await prepare(db_client, account)
    result = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert result.json()["flagged"] == 0


@requires_database
async def test_update_keeps_untouched_fields(db_client: AsyncClient) -> None:
    """Правка одного поля не должна затирать остальные значениями по умолчанию."""
    account = await register(db_client)

    added = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "valve",
            "target_term": "клапан",
            "source_language": "en",
            "target_language": "ru",
            "note": "запорная арматура",
            "status": "proposed",
        },
    )
    term_id = added.json()["id"]

    updated = await db_client.patch(
        f"/glossary/{term_id}",
        headers=account.headers,
        json={"status": "confirmed", "reference": "ГОСТ 24856-2014"},
    )

    body = updated.json()

    assert body["status"] == "confirmed"
    assert body["reference"] == "ГОСТ 24856-2014"
    assert body["note"] == "запорная арматура"
    assert body["target_term"] == "клапан"


@requires_database
async def test_candidates_are_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    document_id = await prepare(db_client, owner)
    await extract(db_client, owner, document_id)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    listing = await db_client.get(f"/documents/{document_id}/terminology", headers=stranger.headers)

    assert listing.status_code == 200
    assert listing.json() == []


@requires_database
async def test_extract_needs_parsed_document(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )
    document_id = uploaded.json()["id"]

    response = await db_client.post(
        f"/documents/{document_id}/terminology/extract", headers=account.headers
    )

    assert response.status_code == 409
