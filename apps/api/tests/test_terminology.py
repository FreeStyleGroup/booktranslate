"""Терминологический проход через API.

Проверяется то, ради чего он существует: словарь книги решается до перевода,
решение переживает повторный проход, а неустоявшийся термин не выдаётся за
ошибку перевода.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker as worker_module
from app.services.providers import TranslationRequest
from tests.chapters import (
    approve_glossary,
    block_rows,
    decide_terms,
    open_book,
    translate,
    uploaded_book,
    with_masters,
)
from tests.conftest import RecordingProvider, requires_database
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
    """Глава с извлечённым мастером: по нему собираются кандидаты."""
    book = await uploaded_book(client, account, data=data)
    extracted = await client.post(
        f"/chapters/{book.chapter}/masters", headers=account.headers, json={"reason": None}
    )
    assert extracted.status_code == 201, extracted.text

    return book.chapter


async def extract(client: AsyncClient, account: Account, chapter_id: str) -> list[dict]:
    response = await client.post(
        f"/chapters/{chapter_id}/terminology/extract", headers=account.headers
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
    chapter_id = await prepare(db_client, account)

    candidates = await extract(db_client, account, chapter_id)

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
async def test_accepted_term_reaches_translation(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Принятый термин доезжает до модели через утверждённую версию глоссария."""
    log: list[TranslationRequest] = []
    monkeypatch.setattr(worker_module, "get_provider", lambda _model=None: RecordingProvider(log))

    account = await register(db_client)
    book = await open_book(
        db_client, account, data=MANUAL, accepted={"check valve": "обратный клапан"}
    )

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()["items"]
    terms = {item["source_term"]: item for item in glossary}

    assert terms["check valve"]["source"] == "extracted"
    assert terms["check valve"]["status"] == "confirmed"

    await translate(db_client, session, account, book.chapter)

    assert any(term.target == "обратный клапан" for request in log for term in request.terms)

    rows = await block_rows(db_client, account, book.chapter)
    assert "обратный клапан" in rows[0]["current"]["text"]


@requires_database
async def test_do_not_translate_needs_no_target(db_client: AsyncClient) -> None:
    account = await register(db_client)
    chapter_id = await prepare(db_client, account)
    candidates = await extract(db_client, account, chapter_id)

    decisions = [
        {
            "candidate_id": by_source(candidates, "check valve")["id"],
            "accept": True,
            "target_term": "обратный клапан",
        },
        # Непереводимому перевод не нужен: он совпадает с исходным.
        {"candidate_id": by_source(candidates, "ISO 9001")["id"], "accept": True},
    ]

    report = await db_client.post(
        f"/chapters/{chapter_id}/terminology/decisions",
        headers=account.headers,
        json={"decisions": decisions},
    )
    assert report.status_code == 200, report.text
    assert report.json() == {"accepted": 2, "rejected": 0, "remaining": 0}

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()["items"]
    terms = {item["source_term"]: item for item in glossary}

    # У непереводимого перевод подставлен сам, копировать строку не пришлось.
    assert terms["ISO 9001"]["target_term"] == "ISO 9001"


@requires_database
async def test_abbreviation_keeps_expansion_in_note(db_client: AsyncClient) -> None:
    """Расшифровка из текста уезжает в примечание к термину, а не теряется."""
    account = await register(db_client)
    chapter_id = await prepare(
        db_client,
        account,
        data=(
            b"The Programmable Logic Controller (PLC) runs the cycle.\n\nReplace the PLC module.\n"
        ),
    )

    candidates = await extract(db_client, account, chapter_id)
    plc = by_source(candidates, "PLC")

    assert plc["kind"] == "abbreviation"
    assert plc["expansion"] == "Programmable Logic Controller"

    await db_client.post(
        f"/chapters/{chapter_id}/terminology/decisions",
        headers=account.headers,
        json={"decisions": [{"candidate_id": plc["id"], "accept": True, "target_term": "ПЛК"}]},
    )

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()["items"]
    term = next(item for item in glossary if item["source_term"] == "PLC")

    assert term["note"] == "Programmable Logic Controller"
    # Аббревиатуру при первом употреблении принято раскрывать — это правило
    # технического текста, и по умолчанию оно включено.
    assert term["first_use_rule"] == "expand"


@requires_database
async def test_rejected_candidate_does_not_come_back(db_client: AsyncClient) -> None:
    """Иначе на повторном проходе редактор увидит те же строки заново."""
    account = await register(db_client)
    chapter_id = await prepare(db_client, account)
    candidates = await extract(db_client, account, chapter_id)

    await db_client.post(
        f"/chapters/{chapter_id}/terminology/decisions",
        headers=account.headers,
        json={
            "decisions": [
                {"candidate_id": by_source(candidates, "check valve")["id"], "accept": False}
            ]
        },
    )

    again = await extract(db_client, account, chapter_id)

    assert by_source(again, "check valve")["status"] == "rejected"


@requires_database
async def test_retired_term_does_not_enter_the_version(db_client: AsyncClient) -> None:
    account = await register(db_client)

    book = await uploaded_book(db_client, account, data=MANUAL)
    await with_masters(db_client, account, book)
    await decide_terms(db_client, account, book.chapter, {"check valve": "обратный клапан"})

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()["items"]
    term_id = next(item["id"] for item in glossary if item["source_term"] == "check valve")

    retired = await db_client.patch(
        f"/glossary/{term_id}", headers=account.headers, json={"status": "retired"}
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "retired"

    version = await approve_glossary(db_client, account, book.book_id)

    assert version["term_count"] == 0


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
    chapter_id = await prepare(db_client, owner)
    await extract(db_client, owner, chapter_id)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    listing = await db_client.get(f"/chapters/{chapter_id}/terminology", headers=stranger.headers)

    assert listing.status_code == 404


@requires_database
async def test_extract_needs_a_master(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book = await uploaded_book(db_client, account, data=MANUAL)

    response = await db_client.post(
        f"/chapters/{book.chapter}/terminology/extract", headers=account.headers
    )

    assert response.status_code == 409


@requires_database
async def test_glossary_term_refuses_foreign_project(db_client: AsyncClient) -> None:
    """Термин нельзя привязать к проекту другой организации.

    Запись легла бы в свою организацию, но внешним ключом держалась бы за
    чужой проект: его удаление каскадом унесло бы наши термины, а разница
    между ошибкой ключа и успехом подсказывала бы, существует ли чужой
    идентификатор. Чужое здесь — 404, как и везде.
    """
    owner = await register(db_client)
    foreign_project = await create_project(db_client, owner)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    response = await db_client.post(
        "/glossary",
        headers=stranger.headers,
        json={
            "source_term": "Check Valve",
            "target_term": "обратный клапан",
            "source_language": "en",
            "target_language": "ru",
            "project_id": foreign_project,
        },
    )

    assert response.status_code == 404, response.text
