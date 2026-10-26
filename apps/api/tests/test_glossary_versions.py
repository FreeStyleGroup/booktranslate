"""Версии глоссария и гейт терминологии: от кандидатов главы до открытого перевода."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import masters as masters_module
from app.services.parsers import ParsedBlock, ParsedItem
from app.services.parsers.markup import EpubParser
from tests.conftest import requires_database
from tests.factories import Account, create_project, epub_bytes, register
from tests.test_team import accept_as_new, invite, token_of

FIRST = (
    "<h1>1 Pumps</h1>"
    "<p>The relief valve protects the pump.</p>"
    "<p>Check the relief valve daily.</p>"
    "<pre># open the relief valve\nopen(relief)</pre>"
)
SECOND = (
    "<h1>2 Service</h1>"
    "<p>Replace the relief valve every year.</p>"
    "<p>The relief valve log is kept.</p>"
)

VALVE = "relief valve"


async def book(client: AsyncClient, account: Account) -> tuple[str, list[dict]]:
    """Книга EPUB из двух глав с утверждёнными границами."""
    project_id = await create_project(client, account)
    created = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "Pumps"}
    )
    book_id: str = created.json()["id"]

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={
            "file": (
                "pumps.epub",
                epub_bytes([("part01.xhtml", FIRST), ("part02.xhtml", SECOND)]),
                "application/epub+zip",
            )
        },
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    for step in ("proposal", "approval"):
        response = await client.post(f"/books/{book_id}/chapters/{step}", headers=account.headers)
        assert response.status_code == 200, response.text

    chapters: list[dict] = response.json()["chapters"]
    return book_id, chapters


async def extract_master(
    client: AsyncClient, account: Account, chapter_id: str, reason: str | None = None
) -> dict:
    response = await client.post(
        f"/chapters/{chapter_id}/masters", headers=account.headers, json={"reason": reason}
    )
    assert response.status_code == 201, response.text

    master: dict = response.json()
    return master


async def collect(client: AsyncClient, account: Account, chapter_id: str) -> list[dict]:
    response = await client.post(
        f"/chapters/{chapter_id}/terminology/extract?min_frequency=2", headers=account.headers
    )
    assert response.status_code == 200, response.text

    candidates: list[dict] = response.json()
    return candidates


async def decide(
    client: AsyncClient, account: Account, chapter_id: str, candidates: list[dict]
) -> dict:
    """Принять «relief valve», остальное отклонить."""
    decisions = [
        {
            "candidate_id": item["id"],
            "accept": True,
            "target_term": "предохранительный клапан",
            "allowed_variants": ["клапан сброса"],
            "domain": "гидравлика",
        }
        if item["source_term"].casefold() == VALVE
        else {"candidate_id": item["id"], "accept": False}
        for item in candidates
        if item["status"] == "new"
    ]
    if not decisions:
        return {"remaining": 0}

    response = await client.post(
        f"/chapters/{chapter_id}/terminology/decisions",
        headers=account.headers,
        json={"decisions": decisions},
    )
    assert response.status_code == 200, response.text

    report: dict = response.json()
    return report


async def gate(client: AsyncClient, account: Account, chapter_id: str) -> dict:
    response = await client.get(f"/chapters/{chapter_id}/terminology/gate", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


def codes(items: list[dict]) -> set[str]:
    return {item["code"] for item in items}


async def draft(
    client: AsyncClient, account: Account, book_id: str, chapter_id: str | None = None
) -> dict:
    response = await client.post(
        f"/books/{book_id}/glossary-versions",
        headers=account.headers,
        json={"chapter_id": chapter_id},
    )
    assert response.status_code == 201, response.text

    version: dict = response.json()
    return version


async def detail(client: AsyncClient, account: Account, version_id: str) -> dict:
    response = await client.get(f"/glossary-versions/{version_id}", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


async def approve(
    client: AsyncClient, account: Account, version_id: str, reason: str | None = None
) -> tuple[int, dict]:
    response = await client.post(
        f"/glossary-versions/{version_id}/approval",
        headers=account.headers,
        json={"empty_reason": reason},
    )

    body: dict = response.json()
    return response.status_code, body


async def ready_book(client: AsyncClient, account: Account) -> tuple[str, list[dict]]:
    """Книга с мастерами и решёнными кандидатами обеих глав."""
    book_id, chapters = await book(client, account)

    for chapter in chapters:
        await extract_master(client, account, chapter["id"])
        await decide(client, account, chapter["id"], await collect(client, account, chapter["id"]))

    return book_id, chapters


@requires_database
async def test_gate_opens_only_with_an_approved_version(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book_id, chapters = await book(db_client, account)
    first = chapters[0]["id"]

    closed = await gate(db_client, account, first)
    assert closed["open"] is False
    assert codes(closed["blockers"]) == {"master_missing", "no_approved_version"}

    for chapter in chapters:
        await extract_master(db_client, account, chapter["id"])

    # Нет кандидатов — не значит «терминов нет»: прохода не было.
    unread = await gate(db_client, account, first)
    assert codes(unread["blockers"]) == {"terms_not_collected", "no_approved_version"}

    candidates = await collect(db_client, account, first)
    valve = next(item for item in candidates if item["source_term"].casefold() == VALVE)
    # Первое вхождение — блоком с кодом, а не номером сегмента. Листинг в
    # проход не идёт: идентификатор в коде — не термин.
    assert valve["first_block_code"].startswith("CH01-B")
    assert valve["frequency"] == 2

    undecided = await gate(db_client, account, first)
    assert "candidates_undecided" in codes(undecided["blockers"])

    # Черновик собирается, но утвердить его нельзя, пока решения не приняты.
    early = await draft(db_client, account, book_id)
    blocked = await detail(db_client, account, early["id"])
    assert {"candidates_undecided", "terms_not_collected"} <= codes(blocked["blockers"])
    status, body = await approve(db_client, account, early["id"])
    assert status == 409, body

    await decide(db_client, account, first, candidates)
    second = chapters[1]["id"]
    # Решённое в первой главе во второй не спрашивают заново.
    later = await collect(db_client, account, second)
    repeated = next(item for item in later if item["source_term"].casefold() == VALVE)
    decided = await db_client.get(f"/chapters/{first}/terminology", headers=account.headers)
    original = next(item for item in decided.json() if item["id"] == valve["id"])
    assert repeated["status"] == "accepted"
    assert repeated["glossary_term_id"] == original["glossary_term_id"] is not None
    await decide(db_client, account, second, later)

    version = await draft(db_client, account, book_id)
    assert version["label"] == "v2"
    assert version["scope"] == "book"
    assert version["term_count"] == 1
    assert (await detail(db_client, account, version["id"]))["blockers"] == []

    status, approved = await approve(db_client, account, version["id"])
    assert status == 200, approved
    assert approved["status"] == "approved"

    opened = await gate(db_client, account, first)
    assert opened["open"] is True
    assert opened["version"]["label"] == "v2"
    assert opened["warnings"] == []

    # Прежний черновик заменён новым и в работу не пошёл.
    overview = await db_client.get(f"/books/{book_id}/terminology", headers=account.headers)
    statuses = {item["label"]: item["status"] for item in overview.json()["versions"]}
    assert statuses == {"v1": "superseded", "v2": "approved"}

    terms = await db_client.get(
        f"/glossary-versions/{version['id']}/terms", headers=account.headers
    )
    (term,) = terms.json()["items"]
    assert term["allowed_variants"] == ["клапан сброса"]
    assert term["domain"] == "гидравлика"


@requires_database
async def test_changed_mandatory_term_lists_the_blocks_it_touches(
    db_client: AsyncClient,
) -> None:
    account = await register(db_client)
    book_id, chapters = await ready_book(db_client, account)
    first = await draft(db_client, account, book_id)
    await approve(db_client, account, first["id"])

    found = await db_client.get(f"/glossary?query={VALVE}", headers=account.headers)
    (term,) = found.json()["items"]
    changed = await db_client.patch(
        f"/glossary/{term['id']}", headers=account.headers, json={"target_term": "клапан сброса"}
    )
    assert changed.status_code == 200, changed.text
    # Основной перевод совпал с прежним вариантом — вариант ушёл из списка.
    assert changed.json()["allowed_variants"] == []

    # Правка словаря не действует, пока не утверждена: глава открыта, но
    # о расхождении сказано.
    pending = await gate(db_client, account, chapters[0]["id"])
    assert pending["open"] is True
    assert codes(pending["warnings"]) == {"glossary_changed"}

    second = await draft(db_client, account, book_id)
    assert second["base_id"] == first["id"]
    assert (await detail(db_client, account, second["id"]))["impacted_blocks"] == 4

    changes = await db_client.get(
        f"/glossary-versions/{second['id']}/changes", headers=account.headers
    )
    (change,) = changes.json()
    assert change["kind"] == "changed"
    assert change["before"]["target_term"] == "предохранительный клапан"
    assert change["after"]["target_term"] == "клапан сброса"
    assert change["blocks"] == 4

    impact = await db_client.get(
        f"/glossary-versions/{second['id']}/impact", headers=account.headers
    )
    blocks = impact.json()["items"]
    assert impact.json()["total"] == 4
    # Листинг с тем же словом не задет: код не переводится.
    assert [item["chapter_code"] for item in blocks] == ["CH01", "CH01", "CH02", "CH02"]
    assert all(item["block"]["kind"] == "paragraph" for item in blocks)
    assert blocks[0]["terms"] == [VALVE]

    status, _ = await approve(db_client, account, second["id"])
    assert status == 200

    overview = await db_client.get(f"/books/{book_id}/terminology", headers=account.headers)
    versions = {item["label"]: item for item in overview.json()["versions"]}
    assert versions["v1"]["status"] == "superseded"
    assert versions["v1"]["superseded_by_id"] == second["id"]
    assert (await gate(db_client, account, chapters[0]["id"]))["warnings"] == []


@requires_database
async def test_new_master_closes_the_gate_of_its_chapter(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    book_id, chapters = await ready_book(db_client, account)
    version = await draft(db_client, account, book_id)
    await approve(db_client, account, version["id"])
    second = chapters[1]["id"]

    # Черновик собран до того, как у второй главы появился новый мастер.
    stale = await draft(db_client, account, book_id)

    monkeypatch.setattr(masters_module, "parser_for", lambda _format: _CorrectedParser())
    await extract_master(db_client, account, second, reason="Исправлен срок в абзаце")

    changed = await gate(db_client, account, second)
    assert changed["open"] is False
    assert codes(changed["blockers"]) == {"terms_not_collected", "master_changed"}
    # Соседняя глава не тронута.
    assert (await gate(db_client, account, chapters[0]["id"]))["open"] is True

    # Решение о прежнем тексте ничего не говорит о новом.
    outdated = (await detail(db_client, account, stale["id"]))["blockers"]
    assert codes(outdated) == {"basis_outdated", "terms_not_collected"}
    status, _ = await approve(db_client, account, stale["id"])
    assert status == 409

    await decide(db_client, account, second, await collect(db_client, account, second))
    fresh = await draft(db_client, account, book_id)
    status, body = await approve(db_client, account, fresh["id"])
    assert status == 200, body
    assert (await gate(db_client, account, second))["open"] is True


class _CorrectedParser:
    """Разбор «после исправления»: в абзаце второй главы сменился год."""

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        for item in EpubParser().parse(path):
            if isinstance(item, ParsedBlock) and item.text.startswith("Replace the relief"):
                yield ParsedBlock(
                    text="Replace the relief valve every month.",
                    kind=item.kind,
                    location=item.location,
                )
            else:
                yield item


@requires_database
async def test_chapter_version_works_until_the_book_decides(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book_id, chapters = await book(db_client, account)
    first, second = chapters[0]["id"], chapters[1]["id"]

    for chapter in chapters:
        await extract_master(db_client, account, chapter["id"])

    # Первую главу можно начать, не дожидаясь второй.
    await decide(db_client, account, first, await collect(db_client, account, first))
    own = await draft(db_client, account, book_id, first)
    assert own["scope"] == "chapter"
    status, _ = await approve(db_client, account, own["id"])
    assert status == 200

    assert (await gate(db_client, account, first))["version"]["id"] == own["id"]
    assert (await gate(db_client, account, second))["open"] is False

    await decide(db_client, account, second, await collect(db_client, account, second))
    whole = await draft(db_client, account, book_id)
    status, _ = await approve(db_client, account, whole["id"])
    assert status == 200

    # Книжная версия — решение о единообразии: главная после неё не действует.
    assert (await gate(db_client, account, first))["version"]["id"] == whole["id"]
    replaced = await detail(db_client, account, own["id"])
    assert replaced["status"] == "superseded"
    assert replaced["superseded_by_id"] == whole["id"]


@requires_database
async def test_empty_version_needs_a_written_decision(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book_id, chapters = await book(db_client, account)

    for chapter in chapters:
        await extract_master(db_client, account, chapter["id"])
        candidates = await collect(db_client, account, chapter["id"])
        response = await db_client.post(
            f"/chapters/{chapter['id']}/terminology/decisions",
            headers=account.headers,
            json={
                "decisions": [{"candidate_id": item["id"], "accept": False} for item in candidates]
            },
        )
        assert response.status_code == 200, response.text

    empty = await draft(db_client, account, book_id)
    assert empty["term_count"] == 0

    status, body = await approve(db_client, account, empty["id"])
    assert status == 400, body

    status, body = await approve(
        db_client, account, empty["id"], reason="Брошюра без специальной терминологии"
    )
    assert status == 200, body
    assert body["empty_reason"] == "Брошюра без специальной терминологии"
    assert (await gate(db_client, account, chapters[0]["id"]))["open"] is True


@requires_database
async def test_unsettled_mandatory_term_blocks_approval(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book_id, _ = await ready_book(db_client, account)

    found = await db_client.get(f"/glossary?query={VALVE}", headers=account.headers)
    term_id = found.json()["items"][0]["id"]
    await db_client.patch(
        f"/glossary/{term_id}", headers=account.headers, json={"status": "needs_unification"}
    )

    version = await draft(db_client, account, book_id)
    blockers = (await detail(db_client, account, version["id"]))["blockers"]
    assert codes(blockers) == {"terms_unsettled"}
    assert VALVE in blockers[0]["message"]


@requires_database
async def test_translator_drafts_but_does_not_approve(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    book_id, _ = await ready_book(db_client, owner)
    translator = Account(
        headers=await accept_as_new(db_client, token_of(await invite(db_client, owner))),
        user_id=owner.user_id,
        organization_id=owner.organization_id,
    )

    version = await draft(db_client, translator, book_id)
    status, body = await approve(db_client, translator, version["id"])
    assert status == 403, body

    status, _ = await approve(db_client, owner, version["id"])
    assert status == 200


@requires_database
async def test_glossary_term_refuses_to_clear_its_translation(db_client: AsyncClient) -> None:
    account = await register(db_client)
    created = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "relief valve",
            "target_term": "предохранительный клапан",
            "source_language": "en",
            "target_language": "ru",
            "first_use_rule": "original",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["first_use_rule"] == "original"

    cleared = await db_client.patch(
        f"/glossary/{created.json()['id']}", headers=account.headers, json={"target_term": None}
    )
    assert cleared.status_code == 400, cleared.text
