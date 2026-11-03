"""Общий словарь площадки: загрузки, разрешение, одобрение, подсказки.

Проверяется то, ради чего это заведено: словарь заказчика остаётся его,
пока он не разрешил иное; площадка одобряет термины в общий словарь под
тематикой; пространство с той же тематикой получает их подсказками — в
списке и в переводе — и своё решение всегда важнее чужого.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker as worker_module
from app.services.providers import TranslationRequest
from app.worker import once
from tests.chapters import STOP, block_rows, uploaded_book, with_masters
from tests.conftest import RecordingProvider, requires_database
from tests.factories import Account, admin_headers, create_project, register
from tests.test_dictionary_import import upload
from tests.test_team import accept_as_new, invite, token_of

GLOSSARY = "source,target\nvalve,клапан\npump,насос\n".encode()


async def set_workspace(client: AsyncClient, account: Account, **fields: Any) -> dict[str, Any]:
    response = await client.put("/settings/workspace", headers=account.headers, json=fields)
    assert response.status_code == 200, response.text

    body: dict[str, Any] = response.json()
    return body


async def feed(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/admin/glossary/uploads", headers=await admin_headers(client))
    assert response.status_code == 200, response.text

    body: dict[str, Any] = response.json()
    return body


async def publish_all(client: AsyncClient, upload_id: str, subject: str) -> int:
    root = await admin_headers(client)

    detail = await client.get(f"/admin/glossary/uploads/{upload_id}", headers=root)
    assert detail.status_code == 200, detail.text

    published = await client.post(
        "/admin/glossary/shared",
        headers=root,
        json={"term_ids": [term["id"] for term in detail.json()["terms"]], "subject": subject},
    )
    assert published.status_code == 200, published.text

    count: int = published.json()["published"]
    return count


@requires_database
async def test_upload_is_recorded_and_lands_in_the_admin_feed(db_client: AsyncClient) -> None:
    """Администратор узнаёт, что появился новый словарь, — из ленты, а не из базы."""
    account = await register(db_client)

    report = await upload(db_client, account, data=GLOSSARY, origin="Заказчик")
    assert report["_status"] == 200, report
    assert report["upload"]["shared"] is False
    assert (report["upload"]["added"], report["upload"]["total"]) == (2, 2)

    mine = await db_client.get("/glossary/uploads", headers=account.headers)
    assert [item["origin"] for item in mine.json()] == ["Заказчик"]

    listing = await feed(db_client)
    assert listing["unreviewed"] == 1
    assert listing["items"][0]["organization_name"] == "Бюро переводов"
    assert listing["items"][0]["uploaded_by"] == "owner@example.com"
    assert listing["items"][0]["shared"] is False


@requires_database
async def test_terms_stay_private_without_consent(db_client: AsyncClient) -> None:
    """Без разрешения администратор видит факт загрузки и числа, но не слова."""
    account = await register(db_client)
    report = await upload(db_client, account, data=GLOSSARY)

    detail = await db_client.get(
        f"/admin/glossary/uploads/{report['upload']['id']}",
        headers=await admin_headers(db_client),
    )

    assert detail.status_code == 403
    assert "не разрешило" in detail.json()["detail"]

    # И подделанный запрос на одобрение по идентификаторам ничего не выносит.
    terms = (await db_client.get("/glossary", headers=account.headers)).json()["items"]
    published = await db_client.post(
        "/admin/glossary/shared",
        headers=await admin_headers(db_client),
        json={"term_ids": [term["id"] for term in terms], "subject": "engineering"},
    )

    assert published.json()["published"] == 0


@requires_database
async def test_consent_is_given_at_upload_and_remembered(db_client: AsyncClient) -> None:
    account = await register(db_client)

    report = await upload(db_client, account, data=GLOSSARY, share="true")
    assert report["upload"]["shared"] is True

    settings = await db_client.get("/settings/workspace", headers=account.headers)
    assert settings.json()["share_glossary"] is True

    # Следующая загрузка без явного ответа идёт по запомненному.
    again = await upload(db_client, account, data="source,target\nrotor,ротор\n".encode())
    assert again["upload"]["shared"] is True


@requires_database
async def test_only_workspace_admin_changes_consent(db_client: AsyncClient) -> None:
    """Разрешение — распоряжение чужими данными, а не работа с текстом."""
    owner = await register(db_client)
    invited = await invite(db_client, owner, role="translator")
    translator = Account(
        headers=await accept_as_new(db_client, token_of(invited)),
        user_id=owner.user_id,
        organization_id=owner.organization_id,
    )

    refused = await upload(db_client, translator, data=GLOSSARY, share="true")
    assert refused["_status"] == 403, refused
    assert "владелец или администратор" in refused["detail"]

    # Без явного ответа переводчик грузит под настройкой пространства.
    allowed = await upload(db_client, translator, data=GLOSSARY)
    assert allowed["_status"] == 200, allowed
    assert allowed["upload"]["shared"] is False


@requires_database
async def test_approved_terms_become_suggestions_for_the_same_subject(
    db_client: AsyncClient,
) -> None:
    """Одобренное площадкой видит пространство с той же тематикой — и только оно."""
    donor = await register(db_client)
    report = await upload(db_client, donor, data=GLOSSARY, share="true")

    assert await publish_all(db_client, report["upload"]["id"], "engineering") == 2

    listing = await feed(db_client)
    assert listing["items"][0]["subject"] is None

    taker = await register(db_client, email="taker@example.com", organization_name="Другое бюро")
    await create_project(db_client, taker)

    # Без тематики подсказок нет, и ответ говорит почему.
    empty = (await db_client.get("/glossary/suggestions", headers=taker.headers)).json()
    assert empty == {"subject": None, "items": []}

    await set_workspace(db_client, taker, subject="finance")
    other = (await db_client.get("/glossary/suggestions", headers=taker.headers)).json()
    assert other["items"] == []

    await set_workspace(db_client, taker, subject="engineering")
    same = (await db_client.get("/glossary/suggestions", headers=taker.headers)).json()
    assert same["subject"] == "engineering"
    assert [item["source_term"] for item in same["items"]] == ["pump", "valve"]

    # Своё решение снимает подсказку.
    added = await db_client.post(
        "/glossary",
        headers=taker.headers,
        json={
            "source_term": "valve",
            "target_term": "вентиль",
            "source_language": "en",
            "target_language": "ru",
        },
    )
    assert added.status_code == 201, added.text

    left = (await db_client.get("/glossary/suggestions", headers=taker.headers)).json()
    assert [item["source_term"] for item in left["items"]] == ["pump"]


@requires_database
async def test_accepted_suggestion_becomes_own_confirmed_term(db_client: AsyncClient) -> None:
    donor = await register(db_client)
    report = await upload(db_client, donor, data=GLOSSARY, share="true")
    await publish_all(db_client, report["upload"]["id"], "engineering")

    taker = await register(db_client, email="taker@example.com", organization_name="Другое бюро")
    await create_project(db_client, taker)
    await set_workspace(db_client, taker, subject="engineering")

    suggestions = (await db_client.get("/glossary/suggestions", headers=taker.headers)).json()
    pump = next(item for item in suggestions["items"] if item["source_term"] == "pump")

    accepted = await db_client.post(f"/glossary/suggestions/{pump['id']}", headers=taker.headers)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["source"] == "platform"
    assert accepted.json()["status"] == "confirmed"

    left = (await db_client.get("/glossary/suggestions", headers=taker.headers)).json()
    assert [item["source_term"] for item in left["items"]] == ["valve"]


@requires_database
async def test_shared_terms_reach_the_model_as_hints_but_own_decision_wins(
    db_client: AsyncClient,
    session: AsyncSession,
    provider_log: list[TranslationRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без утверждённой версии перевод идёт по рабочему словарю, и общий словарь в нём —
    подсказка, а не требование, а своё слово заказчика вытесняет чужое."""
    monkeypatch.setattr(
        worker_module, "get_provider", lambda _model=None: RecordingProvider(provider_log)
    )

    donor = await register(db_client)
    report = await upload(db_client, donor, data=GLOSSARY, share="true")
    await publish_all(db_client, report["upload"]["id"], "engineering")

    taker = await register(db_client, email="taker@example.com", organization_name="Другое бюро")
    await set_workspace(db_client, taker, subject="engineering")

    own = await db_client.post(
        "/glossary",
        headers=taker.headers,
        json={
            "source_term": "valve",
            "target_term": "вентиль",
            "source_language": "en",
            "target_language": "ru",
        },
    )
    assert own.status_code == 201, own.text

    book = await uploaded_book(db_client, taker, data=b"Open the valve and start the pump.\n")
    await with_masters(db_client, taker, book)

    started = await db_client.post(
        f"/chapters/{book.chapter}/translation",
        headers=taker.headers,
        json={"ignore_terminology": True, "reason": "Пробная глава до согласования терминов"},
    )
    assert started.status_code == 201, started.text
    assert await once(session, "test", STOP) is True

    terms = {term.source: term for term in provider_log[-1].terms}
    assert terms["valve"].target == "вентиль"
    assert terms["valve"].mandatory is True
    assert terms["pump"].target == "насос"
    assert terms["pump"].mandatory is False
    assert terms["pump"].settled is False

    # Заглушка подставляет термины — и общий тоже.
    rows = await block_rows(db_client, taker, book.chapter)
    assert "вентиль" in rows[0]["current"]["text"]


@requires_database
async def test_admin_reviews_uploads_and_manages_the_shared_glossary(
    db_client: AsyncClient,
) -> None:
    donor = await register(db_client)
    report = await upload(db_client, donor, data=GLOSSARY, share="true")
    upload_id = report["upload"]["id"]
    root = await admin_headers(db_client)

    reviewed = await db_client.post(f"/admin/glossary/uploads/{upload_id}/reviewed", headers=root)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_by"] == "root@example.com"
    assert (await feed(db_client))["unreviewed"] == 0

    await publish_all(db_client, upload_id, "engineering")
    # Повторное одобрение уточняет, а не удваивает.
    await publish_all(db_client, upload_id, "engineering")

    shared = await db_client.get(
        "/admin/glossary/shared", headers=root, params={"subject": "engineering"}
    )
    assert shared.json()["total"] == 2

    found = await db_client.get("/admin/glossary/shared", headers=root, params={"query": "насо"})
    assert [item["source_term"] for item in found.json()["items"]] == ["pump"]

    removed = await db_client.delete(
        f"/admin/glossary/shared/{found.json()['items'][0]['id']}", headers=root
    )
    assert removed.status_code == 204

    assert (await db_client.get("/admin/glossary/shared", headers=root)).json()["total"] == 1


@requires_database
async def test_unknown_subject_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.put(
        "/settings/workspace", headers=account.headers, json={"subject": "astrology"}
    )

    assert response.status_code == 400
    assert "нет в списке" in response.json()["detail"]


@requires_database
async def test_glossary_page_filters_and_counts(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await upload(db_client, account, data=GLOSSARY)

    page = await db_client.get(
        "/glossary", headers=account.headers, params={"query": "кла", "limit": 1}
    )
    body = page.json()

    assert body["total"] == 1
    assert [item["source_term"] for item in body["items"]] == ["valve"]

    proposed = await db_client.get(
        "/glossary", headers=account.headers, params={"status": "proposed"}
    )
    assert proposed.json()["total"] == 2

    confirmed = await db_client.get(
        "/glossary", headers=account.headers, params={"status": "confirmed"}
    )
    assert confirmed.json()["total"] == 0
