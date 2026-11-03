"""Перевод главы: прогоны, неизменяемые редакции, перевод заново, защита объектов."""

import asyncio
import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker as worker_module
from app.models.audit import AuditEvent
from app.models.job import JobState, TranslationJob
from app.models.translation import TranslationRevision, TranslationRun
from app.services.providers import StubProvider, Translated, TranslationRequest
from app.worker import once
from tests.conftest import requires_database
from tests.factories import Account, create_project, epub_bytes, register
from tests.test_glossary_versions import approve, collect, decide, draft, extract_master, gate
from tests.test_team import accept_as_new, invite, token_of

CHAPTER = (
    "<h1>1 Pumps</h1>"
    "<p>The relief valve protects the pump.</p>"
    "<p>Check the relief valve daily.</p>"
    "<p>Check the relief valve daily.</p>"
    "<p>Radius <math><mi>r</mi><mn>2</mn></math> is set by <code>radius(x)</code>.</p>"
    "<pre># open the relief valve\n    open(relief)  </pre>"
    "<table><tr><td>Pressure</td><td>12,5</td></tr></table>"
)
SECOND = "<h1>2 Service</h1><p>Check the relief valve daily.</p><p>The relief valve log.</p>"

STOP = asyncio.Event()


async def ready(
    client: AsyncClient, account: Account, *, first_use: str | None = None
) -> tuple[str, list[dict]]:
    """Книга, в которой главу уже можно переводить.

    `first_use` — правило первого употребления у «relief valve»: оно попадает в
    утверждаемую версию глоссария, поэтому задаётся до неё.
    """
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
                epub_bytes([("part01.xhtml", CHAPTER), ("part02.xhtml", SECOND)]),
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

    for chapter in chapters:
        master = await extract_master(client, account, chapter["id"])
        approved = await client.post(f"/masters/{master['id']}/approval", headers=account.headers)
        assert approved.status_code == 200, approved.text
        await decide(client, account, chapter["id"], await collect(client, account, chapter["id"]))

    if first_use is not None:
        terms = await client.get("/glossary?query=relief", headers=account.headers)
        assert terms.status_code == 200, terms.text
        ruled = await client.patch(
            f"/glossary/{terms.json()['items'][0]['id']}",
            headers=account.headers,
            json={"first_use_rule": first_use},
        )
        assert ruled.status_code == 200, ruled.text

    version = await draft(client, account, book_id)
    status, body = await approve(client, account, version["id"])
    assert status == 200, body

    return book_id, chapters


async def start(client: AsyncClient, account: Account, chapter_id: str) -> dict:
    response = await client.post(
        f"/chapters/{chapter_id}/translation", headers=account.headers, json={}
    )
    assert response.status_code == 201, response.text

    run: dict = response.json()
    return run


async def blocks(client: AsyncClient, account: Account, chapter_id: str) -> list[dict]:
    response = await client.get(
        f"/chapters/{chapter_id}/translation/blocks?limit=200", headers=account.headers
    )
    assert response.status_code == 200, response.text

    items: list[dict] = response.json()["items"]
    return items


async def history(client: AsyncClient, account: Account, block_id: str) -> list[dict]:
    response = await client.get(f"/blocks/{block_id}/revisions", headers=account.headers)
    assert response.status_code == 200, response.text

    items: list[dict] = response.json()["items"]
    return items


async def translate(
    client: AsyncClient, session: AsyncSession, account: Account, chapter_id: str
) -> dict:
    await start(client, account, chapter_id)
    assert await once(session, "test", STOP) is True

    return await readiness(client, account, chapter_id)


async def readiness(client: AsyncClient, account: Account, chapter_id: str) -> dict:
    response = await client.get(f"/chapters/{chapter_id}/translation", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


class Scripted(StubProvider):
    """Заглушка, отвечающая по сценарию и запоминающая запросы."""

    def __init__(self, change: Callable[[dict[str, str]], dict[str, str]] | None = None) -> None:
        self.calls: list[list[TranslationRequest]] = []
        self._change = change

    async def translate(self, requests: list[TranslationRequest]) -> Translated:
        self.calls.append(list(requests))
        answer = await super().translate(requests)

        return Translated(items=self._change(answer.items) if self._change else answer.items)


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Scripted]:
    def install(change: Callable[[dict[str, str]], dict[str, str]] | None = None) -> Scripted:
        provider = Scripted(change)
        monkeypatch.setattr(worker_module, "get_provider", lambda _model=None: provider)

        return provider

    return install


@requires_database
async def test_gate_holds_the_chapter_until_everything_is_decided(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    created = await db_client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "Pumps"}
    )
    book_id = created.json()["id"]
    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={
            "file": ("p.epub", epub_bytes([("a.xhtml", SECOND)]), "application/epub+zip"),
        },
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    for step in ("proposal", "approval"):
        response = await db_client.post(
            f"/books/{book_id}/chapters/{step}", headers=account.headers
        )
    chapter_id = response.json()["chapters"][0]["id"]
    master = await extract_master(db_client, account, chapter_id)

    closed = await readiness(db_client, account, chapter_id)
    assert closed["open"] is False
    assert {item["code"] for item in closed["blockers"]} >= {
        "master_not_approved",
        "no_approved_version",
    }
    # Мастер не утверждён — обойти это нельзя: вопрос не о терминах.
    assert closed["bypassable"] is False

    refused = await db_client.post(
        f"/chapters/{chapter_id}/translation",
        headers=account.headers,
        json={"ignore_terminology": True, "reason": "Заказчик торопит с выпуском главы"},
    )
    assert refused.status_code == 409

    await db_client.post(f"/masters/{master['id']}/approval", headers=account.headers)

    after = await readiness(db_client, account, chapter_id)
    assert after["bypassable"] is True


@requires_database
async def test_chapter_is_translated_into_immutable_revisions(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    assert (await gate(db_client, account, chapter_id))["open"] is True

    state = await readiness(db_client, account, chapter_id)
    assert state["open"] is True
    assert state["translated"] == 0

    run = await start(db_client, account, chapter_id)
    assert run["state"] == "waiting"
    assert run["kind"] == "draft"
    assert run["prompt_version"] == "stub"
    assert run["glossary_label"] == "v1"

    assert await once(session, "test", STOP) is True

    state = await readiness(db_client, account, chapter_id)
    assert state["pending"] == 0
    assert state["live"] is None

    latest = state["latest"]
    assert latest["state"] == "done"
    assert latest["blocks_done"] == latest["blocks_total"]
    assert latest["rejections"] == []

    rows = await blocks(db_client, account, chapter_id)
    assert all(row["current"] is not None for row in rows)

    # Для каждой редакции известны модель, промпт, глоссарий и прогон.
    entries = await history(db_client, account, rows[1]["id"])
    assert len(entries) == 1
    assert entries[0]["model"] == "stub"
    assert entries[0]["prompt_version"] == "stub"
    assert entries[0]["glossary_label"] == "v1"
    assert entries[0]["run_id"] == run["id"]
    assert entries[0]["current"] is True


@requires_database
async def test_listing_is_copied_byte_for_byte_and_never_sent(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    provider = scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    await translate(db_client, session, account, chapter_id)

    rows = await blocks(db_client, account, chapter_id)
    listing = next(row for row in rows if row["kind"] == "code")
    number = next(row for row in rows if row["source_text"] == "12,5")

    assert listing["protected"] is True
    assert listing["current"]["text"] == listing["source_text"]
    assert listing["current"]["text"] == "# open the relief valve\n    open(relief)  "
    assert listing["current"]["origin"] == "copy"
    assert number["current"]["origin"] == "copy"

    sent = [request.source_text for call in provider.calls for request in call]
    assert not any("open(relief)" in item for item in sent)
    assert "12,5" not in sent


@requires_database
async def test_inline_formula_and_code_reach_the_model_as_tokens(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    provider = scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    await translate(db_client, session, account, chapter_id)

    sent = [request for call in provider.calls for request in call]
    request = next(item for item in sent if item.source_text.startswith("Radius"))
    assert request.source_text == "Radius ⟦1⟧ is set by ⟦2⟧."
    assert request.key.startswith("CH01-B")

    rows = await blocks(db_client, account, chapter_id)
    row = next(item for item in rows if item["source_text"].startswith("Radius"))
    assert row["current"]["text"] == "[ru] Radius r2 is set by radius(x)."


@requires_database
async def test_neighbours_and_heading_reach_the_model(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    provider = scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)

    await translate(db_client, session, account, chapters[0]["id"])

    sent = [request for call in provider.calls for request in call]
    request = next(item for item in sent if item.source_text.startswith("The relief valve"))

    assert request.context.heading == "1 Pumps"
    assert request.context.before == ("1 Pumps",)
    assert request.context.after[0] == "Check the relief valve daily."

    # Заголовок сам себе не заголовок: иначе модель получит его дважды.
    title = next(item for item in sent if item.source_text == "1 Pumps")
    assert title.context.heading is None
    assert title.context.before == ()


@requires_database
async def test_first_use_goes_to_the_first_occurrence_in_each_chapter(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    provider = scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account, first_use="expand")

    await translate(db_client, session, account, chapters[0]["id"])

    first = [request for call in provider.calls for request in call]
    ruled = [item for item in first if item.first_use]
    assert [item.source_text for item in ruled] == ["The relief valve protects the pump."]
    assert ruled[0].first_use == ("relief valve",)

    provider.calls.clear()
    await translate(db_client, session, account, chapters[1]["id"])

    # Область — глава: во второй главе объяснять снова. Этот текст в книге уже
    # переведён, но повтором он не закрывается: там термин без объяснения.
    second = {request.source_text: request.first_use for call in provider.calls for request in call}
    assert second["Check the relief valve daily."] == ("relief valve",)
    assert second["The relief valve log."] == ()


@requires_database
async def test_lost_token_is_retried_then_block_stays_without_revision(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    def lose(items: dict[str, str]) -> dict[str, str]:
        return {key: text.replace("⟦2⟧", "") for key, text in items.items()}

    provider = scripted(lose)
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    state = await translate(db_client, session, account, chapter_id)

    latest = state["latest"]
    assert latest["state"] == "done"
    assert len(latest["rejections"]) == 1
    assert "⟦2⟧" in latest["rejections"][0]["reason"]
    assert state["pending"] == 1

    # Вторая попытка была — и частью одной, а не всей пачкой.
    sizes = [len(call) for call in provider.calls]
    assert sizes[-1] == 1

    rows = await blocks(db_client, account, chapter_id)
    row = next(item for item in rows if item["source_text"].startswith("Radius"))
    assert row["current"] is None


@requires_database
async def test_extra_and_missing_codes_are_rejected(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    """Лишний код — отказ, и виновный находится делением пачки пополам."""

    def tamper(items: dict[str, str]) -> dict[str, str]:
        if any("protects" in text for text in items.values()):
            return {**items, "CH99-B0001/0": "чужой перевод"}

        return items

    scripted(tamper)
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    state = await translate(db_client, session, account, chapter_id)

    rejected = state["latest"]["rejections"]
    assert len(rejected) == 1
    assert "лишние коды" in rejected[0]["reason"]

    rows = await blocks(db_client, account, chapter_id)
    assert not any(row["current"] and "чужой" in row["current"]["text"] for row in rows)
    good = [row for row in rows if row["current"] is not None]
    assert len(good) == len(rows) - 1


@requires_database
async def test_same_text_is_translated_once_and_reused_in_the_book(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    provider = scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)

    await translate(db_client, session, account, chapters[0]["id"])

    sent = [request.source_text for call in provider.calls for request in call]
    assert sent.count("Check the relief valve daily.") == 1

    first_rows = await blocks(db_client, account, chapters[0]["id"])
    repeats = [row for row in first_rows if row["source_text"] == "Check the relief valve daily."]
    assert len(repeats) == 2
    assert len({row["current"]["text"] for row in repeats}) == 1

    provider.calls.clear()
    await translate(db_client, session, account, chapters[1]["id"])

    sent = [request.source_text for call in provider.calls for request in call]
    assert "Check the relief valve daily." not in sent

    second_rows = await blocks(db_client, account, chapters[1]["id"])
    reused = next(row for row in second_rows if row["source_text"].startswith("Check"))
    assert reused["current"]["origin"] == "memory"
    assert reused["current"]["text"] == repeats[0]["current"]["text"]

    entries = await history(db_client, account, reused["id"])
    assert entries[0]["copied_from_id"] is not None


@requires_database
async def test_retranslate_keeps_the_current_revision_and_adds_a_variant(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    await translate(db_client, session, account, chapter_id)

    rows = await blocks(db_client, account, chapter_id)
    row = next(item for item in rows if item["source_text"].startswith("The relief"))
    base = row["current"]

    scripted(lambda items: {key: f"{text} (вариант)" for key, text in items.items()})

    asked = await db_client.post(
        f"/chapters/{chapter_id}/translation/retranslate",
        headers=account.headers,
        json={"items": [{"block_id": row["id"], "base_revision_id": base["id"]}]},
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["kind"] == "retranslate"
    assert await once(session, "test", STOP) is True

    # Текущая редакция не изменилась, прежний текст на месте.
    after = next(
        item for item in await blocks(db_client, account, chapter_id) if item["id"] == row["id"]
    )
    assert after["current"]["id"] == base["id"]
    assert after["variants"] == 1

    entries = await history(db_client, account, row["id"])
    assert [entry["revision_no"] for entry in entries] == [2, 1]
    variant, previous = entries
    assert variant["current"] is False
    assert variant["supersedes_id"] == previous["id"]
    assert variant["compared_with"] == 1
    assert {"insert", "equal"} <= {item["op"] for item in variant["changes"]}
    assert previous["text"] == base["text"]

    adopted = await db_client.post(f"/revisions/{variant['id']}/adopt", headers=account.headers)
    assert adopted.status_code == 200, adopted.text

    entries = await history(db_client, account, row["id"])
    assert [entry["current"] for entry in entries] == [True, False]
    assert entries[1]["text"] == base["text"]

    # Вариант, созданный относительно прежней текущей, принять больше нельзя.
    stale = await db_client.post(
        f"/chapters/{chapter_id}/translation/retranslate",
        headers=account.headers,
        json={"items": [{"block_id": row["id"], "base_revision_id": base["id"]}]},
    )
    assert stale.status_code == 409


@requires_database
async def test_adopting_a_variant_of_another_text_is_refused(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)

    rows = await blocks(db_client, account, chapter_id)
    row = next(item for item in rows if item["source_text"].startswith("The relief"))
    base_id = row["current"]["id"]

    for _ in range(2):
        asked = await db_client.post(
            f"/chapters/{chapter_id}/translation/retranslate",
            headers=account.headers,
            json={"items": [{"block_id": row["id"], "base_revision_id": base_id}]},
        )
        assert asked.status_code == 201, asked.text
        assert await once(session, "test", STOP) is True

    newest, older, _ = await history(db_client, account, row["id"])

    assert (
        await db_client.post(f"/revisions/{newest['id']}/adopt", headers=account.headers)
    ).status_code == 200

    # Второй вариант сравнивали с редакцией, которая больше не текущая.
    conflict = await db_client.post(f"/revisions/{older['id']}/adopt", headers=account.headers)
    assert conflict.status_code == 409


@requires_database
async def test_database_itself_refuses_to_change_a_revision(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    await translate(db_client, session, account, chapters[0]["id"])

    revision = await session.scalar(select(TranslationRevision).limit(1))
    assert revision is not None
    revision_id = revision.id

    with pytest.raises(DBAPIError, match="неизменяема"):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE translation_revisions SET text = 'подделка' WHERE id = :id"),
                {"id": revision_id},
            )


@requires_database
async def test_one_live_run_per_chapter(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    await start(db_client, account, chapter_id)

    again = await db_client.post(
        f"/chapters/{chapter_id}/translation", headers=account.headers, json={}
    )
    assert again.status_code == 409


@requires_database
async def test_nothing_left_to_translate_is_refused(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)

    again = await db_client.post(
        f"/chapters/{chapter_id}/translation", headers=account.headers, json={}
    )
    assert again.status_code == 409


@requires_database
async def test_cancel_keeps_what_was_paid_for(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    run = await start(db_client, account, chapter_id)
    cancelled = await db_client.post(f"/jobs/{run['job_id']}/cancel", headers=account.headers)
    assert cancelled.status_code == 200, cancelled.text

    state = await readiness(db_client, account, chapter_id)
    assert state["live"] is None
    assert state["latest"]["state"] == "cancelled"
    assert await once(session, "test", STOP) is False


@requires_database
async def test_new_master_stops_the_run(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await start(db_client, account, chapter_id)

    run = await session.scalar(select(TranslationRun).limit(1))
    assert run is not None
    run_id = run.id
    run.master_id = uuid.UUID(
        (
            await db_client.get(f"/chapters/{chapters[1]['id']}/masters", headers=account.headers)
        ).json()[0]["id"]
    )
    await session.commit()

    assert await once(session, "test", STOP) is True

    job = await session.scalar(select(TranslationJob).where(TranslationJob.run_id == run_id))
    assert job is not None
    assert job.state is JobState.FAILED
    assert "новая версия мастера" in (job.error or "")


@requires_database
async def test_bypass_is_for_administrators_with_a_reason(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    created = await db_client.post(
        f"/projects/{project_id}/books", headers=owner.headers, json={"title": "Pumps"}
    )
    book_id = created.json()["id"]
    await db_client.post(
        f"/projects/{project_id}/documents",
        headers=owner.headers,
        files={"file": ("p.epub", epub_bytes([("a.xhtml", SECOND)]), "application/epub+zip")},
        data={"book_id": book_id, "source_role": "primary_text"},
    )

    for step in ("proposal", "approval"):
        response = await db_client.post(f"/books/{book_id}/chapters/{step}", headers=owner.headers)
    chapter_id = response.json()["chapters"][0]["id"]
    master = await extract_master(db_client, owner, chapter_id)
    await db_client.post(f"/masters/{master['id']}/approval", headers=owner.headers)

    plain = await db_client.post(
        f"/chapters/{chapter_id}/translation", headers=owner.headers, json={}
    )
    assert plain.status_code == 409

    no_reason = await db_client.post(
        f"/chapters/{chapter_id}/translation",
        headers=owner.headers,
        json={"ignore_terminology": True, "reason": "коротко"},
    )
    assert no_reason.status_code == 400

    translator = await accept_as_new(
        db_client, token_of(await invite(db_client, owner, role="translator"))
    )
    refused = await db_client.post(
        f"/chapters/{chapter_id}/translation",
        headers=translator,
        json={"ignore_terminology": True, "reason": "Заказчик торопит с выпуском главы"},
    )
    assert refused.status_code == 403

    done = await db_client.post(
        f"/chapters/{chapter_id}/translation",
        headers=owner.headers,
        json={"ignore_terminology": True, "reason": "Заказчик торопит с выпуском главы"},
    )
    assert done.status_code == 201, done.text
    run = done.json()
    assert run["ignore_terminology"] is True
    assert run["glossary_version_id"] is None

    event = await session.scalar(
        select(AuditEvent).where(AuditEvent.kind == "translation.gate_bypassed")
    )
    assert event is not None
    assert event.payload["reason"] == "Заказчик торопит с выпуском главы"
    assert "no_approved_version" in event.payload["blockers"]


@requires_database
async def test_other_workspace_sees_nothing(db_client: AsyncClient, session: AsyncSession) -> None:
    owner = await register(db_client)
    stranger = await register(db_client, email="stranger@example.com")
    _, chapters = await ready(db_client, owner)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, owner, chapter_id)

    rows = await blocks(db_client, owner, chapter_id)

    for path in (
        f"/chapters/{chapter_id}/translation",
        f"/chapters/{chapter_id}/translation/blocks",
        f"/chapters/{chapter_id}/translation/runs",
        f"/blocks/{rows[0]['id']}/revisions",
    ):
        assert (await db_client.get(path, headers=stranger.headers)).status_code == 404

    adopt = await db_client.post(
        f"/revisions/{rows[0]['current']['id']}/adopt", headers=stranger.headers
    )
    assert adopt.status_code == 404


@requires_database
async def test_usage_of_a_run_is_recorded(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.providers import Usage

    class Paid(StubProvider):
        async def translate(self, requests: list[TranslationRequest]) -> Translated:
            answer = await super().translate(requests)

            return Translated(items=answer.items, usage=Usage(input_tokens=10, output_tokens=5))

    monkeypatch.setattr(worker_module, "get_provider", lambda _model=None: Paid())

    account = await register(db_client)
    _, chapters = await ready(db_client, account)

    state = await translate(db_client, session, account, chapters[0]["id"])

    assert state["latest"]["input_tokens"] >= 10
    assert state["latest"]["output_tokens"] >= 5


@requires_database
async def test_technical_check_expires_when_the_translation_changes(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)

    masters = await db_client.get(f"/chapters/{chapter_id}/masters", headers=account.headers)
    objects = await db_client.get(
        f"/masters/{masters.json()[0]['id']}/objects", headers=account.headers
    )
    table = next(item for item in objects.json() if item["type"] == "table")

    detail = (await db_client.get(f"/objects/{table['id']}", headers=account.headers)).json()
    assert detail["verification"]["verified"] is False
    # Перевод ячейки стоит рядом с оригиналом, число перенесено как есть.
    by_text = {cell["text"]: cell["translation"] for cell in detail["content"]}
    assert by_text["12,5"] == "12,5"
    assert by_text["Pressure"] == "[ru] Pressure"

    marked = await db_client.post(f"/objects/{table['id']}/verification", headers=account.headers)
    assert marked.status_code == 200, marked.text
    assert marked.json()["verified"] is True

    detail = (await db_client.get(f"/objects/{table['id']}", headers=account.headers)).json()
    assert detail["verification"]["verified"] is True

    cell = next(item for item in detail["content"] if item["text"] == "Pressure")
    rows = await blocks(db_client, account, chapter_id)
    row = next(item for item in rows if item["id"] == cell["id"])

    asked = await db_client.post(
        f"/chapters/{chapter_id}/translation/retranslate",
        headers=account.headers,
        json={"items": [{"block_id": row["id"], "base_revision_id": row["current"]["id"]}]},
    )
    assert asked.status_code == 201, asked.text
    assert await once(session, "test", STOP) is True

    # Вариант ещё не принят — проверенный текст тот же, и отметка действует.
    detail = (await db_client.get(f"/objects/{table['id']}", headers=account.headers)).json()
    assert detail["verification"]["verified"] is True

    variant = (await history(db_client, account, row["id"]))[0]
    adopted = await db_client.post(f"/revisions/{variant['id']}/adopt", headers=account.headers)
    assert adopted.status_code == 200, adopted.text

    detail = (await db_client.get(f"/objects/{table['id']}", headers=account.headers)).json()
    assert detail["verification"]["verified"] is False
    assert detail["verification"]["outdated"] is True


@requires_database
async def test_untranslated_object_cannot_be_marked_checked(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    masters = await db_client.get(f"/chapters/{chapters[0]['id']}/masters", headers=account.headers)
    objects = await db_client.get(
        f"/masters/{masters.json()[0]['id']}/objects", headers=account.headers
    )
    table = next(item for item in objects.json() if item["type"] == "table")

    refused = await db_client.post(f"/objects/{table['id']}/verification", headers=account.headers)
    assert refused.status_code == 409
