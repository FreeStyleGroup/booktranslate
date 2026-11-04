"""Редактура и финальная сверка: покрытие нынешнего текста, порядок работ, защита при правке."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.block import BlockKind
from app.services.checks import protected_changes
from app.services.glossary import Glossary
from app.worker import once
from tests.conftest import requires_database
from tests.factories import Account, register
from tests.test_chapter_translation import STOP, blocks, history, ready, translate
from tests.test_checks_unit import term
from tests.test_fixes import edit, regression
from tests.test_issues import act, registered
from tests.test_team import accept_as_new, invite, token_of

PARAGRAPH = "The relief valve protects the pump."
RADIUS = "Radius"


async def translated(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, list[dict]]:
    _, chapters = await ready(client, account)
    chapter_id = chapters[0]["id"]
    await translate(client, session, account, chapter_id)

    return chapter_id, await blocks(client, account, chapter_id)


async def start(client: AsyncClient, account: Account, chapter_id: str, kind: str) -> dict:
    response = await client.post(
        f"/chapters/{chapter_id}/reviews", headers=account.headers, json={"kind": kind}
    )
    assert response.status_code == 201, response.text

    body: dict = response.json()
    return body


async def finish(client: AsyncClient, account: Account, run_id: str) -> dict:
    """Пройти всё, что осталось, по очереди и завершить работу."""
    await walk(client, account, run_id)
    response = await client.post(f"/review-runs/{run_id}/complete", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


async def walk(client: AsyncClient, account: Account, run_id: str) -> int:
    marked = 0

    while True:
        found = await client.get(f"/review-runs/{run_id}/next", headers=account.headers)
        assert found.status_code == 200, found.text
        item = found.json()

        if item["block"] is not None:
            done = await client.post(
                f"/review-runs/{run_id}/blocks",
                headers=account.headers,
                json={
                    "block_id": item["block"]["id"],
                    "revision_id": item["block"]["revision_id"],
                },
            )
        elif item["object"] is not None:
            done = await client.post(
                f"/review-runs/{run_id}/objects",
                headers=account.headers,
                json={
                    "object_id": item["object"]["id"],
                    "content_hash": item["object"]["content_hash"],
                },
            )
        else:
            return marked

        assert done.status_code == 200, done.text
        marked += 1


async def read(client: AsyncClient, account: Account, run_id: str) -> dict:
    response = await client.get(f"/review-runs/{run_id}", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


def row_of(rows: list[dict], text_value: str) -> dict:
    return next(row for row in rows if row["source_text"].startswith(text_value))


# ── защита правки: без базы ──


def guard(
    base: str, new: str, *, source: str = "Set 5 mm", glossary: Glossary | None = None
) -> list[str]:
    return protected_changes(source, base, new, glossary=glossary or Glossary([]))


def test_style_change_passes_the_guard() -> None:
    assert guard("Значение равно 5 мм.", "Значение составляет 5 мм.") == []


def test_changed_number_is_caught() -> None:
    assert guard("Значение равно 5 мм.", "Значение равно 7 мм.") != []


def test_lost_sign_is_caught() -> None:
    assert any("знак" in item for item in guard("Ниже -40 °C.", "Ниже 40 °C."))


def test_lost_name_from_code_is_caught() -> None:
    assert any("имена" in item for item in guard("Задайте max_speed.", "Задайте скорость."))


def test_lost_reference_is_caught() -> None:
    assert any("ссылка" in item for item in guard("См. рисунок 3.", "См. ниже. Число 3."))


def test_lost_protected_span_is_caught() -> None:
    changes = protected_changes(
        "Radius r2.", "Радиус r2.", "Радиус.", glossary=Glossary([]), protected=("r2",)
    )
    assert any("защищённые" in item for item in changes)


def test_lost_mandatory_term_is_caught_but_old_gap_is_not_blamed() -> None:
    glossary = Glossary([term("valve", "клапан")])

    new_gap = protected_changes(
        "Open the valve.", "Откройте клапан.", "Откройте вентиль.", glossary=glossary
    )
    assert any("термины" in item for item in new_gap)

    # Термина не было и в прежней редакции: это забота проверок, а не этой правки.
    old_gap = protected_changes(
        "Open the valve.", "Откройте вентиль.", "Вентиль откройте.", glossary=glossary
    )
    assert old_gap == []


# ── порядок и покрытие ──


@requires_database
async def test_work_goes_in_order(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    chapter_id, _ = await translated(db_client, session, account)

    for kind in ("literary", "final_compare"):
        refused = await db_client.post(
            f"/chapters/{chapter_id}/reviews", headers=account.headers, json={"kind": kind}
        )
        assert refused.status_code == 409, kind

    run = await start(db_client, account, chapter_id, "technical")

    twice = await db_client.post(
        f"/chapters/{chapter_id}/reviews", headers=account.headers, json={"kind": "technical"}
    )
    assert twice.status_code == 409

    assert (await finish(db_client, account, run["id"]))["status"] == "completed"

    literary = await start(db_client, account, chapter_id, "literary")
    final_early = await db_client.post(
        f"/chapters/{chapter_id}/reviews", headers=account.headers, json={"kind": "final_compare"}
    )
    assert final_early.status_code == 409

    await finish(db_client, account, literary["id"])
    assert await once(session, "test", STOP) is True

    final = await start(db_client, account, chapter_id, "final_compare")
    done = await finish(db_client, account, final["id"])
    assert done["blocks_done"] == done["blocks_total"]
    assert done["objects_done"] == done["objects_total"] > 0


@requires_database
async def test_cannot_complete_without_full_coverage(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")

    refused = await db_client.post(f"/review-runs/{run['id']}/complete", headers=account.headers)
    assert refused.status_code == 409
    assert "Покрытие" in refused.json()["detail"]

    block = rows[0]
    marked = await db_client.post(
        f"/review-runs/{run['id']}/blocks",
        headers=account.headers,
        json={"block_id": block["id"], "revision_id": block["current"]["id"]},
    )
    assert marked.json()["blocks_done"] == 1
    assert marked.json()["complete"] is False


@requires_database
async def test_mark_is_for_the_text_that_stands_now(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    run = await start(db_client, account, chapter_id, "technical")
    payload = {"block_id": block["id"], "revision_id": block["current"]["id"]}

    first = await db_client.post(
        f"/review-runs/{run['id']}/blocks", headers=account.headers, json=payload
    )
    assert first.json()["blocks_done"] == 1

    again = await db_client.post(
        f"/review-runs/{run['id']}/blocks", headers=account.headers, json=payload
    )
    assert again.status_code == 409

    # Текст изменился: отметка перестала действовать сама, блок снова в очереди.
    issue = await registered(db_client, account, block)
    await act(db_client, account, issue["id"], "confirm")
    await edit(db_client, account, issue["id"], block, "Клапан защищает насос.")

    state = await read(db_client, account, run["id"])
    assert state["blocks_done"] == 0

    stale = await db_client.post(
        f"/review-runs/{run['id']}/blocks", headers=account.headers, json=payload
    )
    assert stale.status_code == 409
    assert "изменился" in stale.json()["detail"]

    found = (await db_client.get(f"/review-runs/{run['id']}/next", headers=account.headers)).json()
    assert found["block"] is not None


@requires_database
async def test_next_goes_through_blocks_then_objects_with_context(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, _ = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")

    found = (await db_client.get(f"/review-runs/{run['id']}/next", headers=account.headers)).json()
    assert found["block"]["code"] == "CH01-B0001"
    assert found["block"]["context"][0]["source_text"] == PARAGRAPH

    after = found["block"]["ordinal"]
    second = (
        await db_client.get(f"/review-runs/{run['id']}/next?after={after}", headers=account.headers)
    ).json()
    assert second["block"]["code"] == "CH01-B0002"
    assert [term_row["source"] for term_row in second["block"]["terms"]] == ["relief valve"]
    assert second["block"]["protected"] is False
    assert second["block"]["context"][0]["ordinal"] == found["block"]["ordinal"]

    marked = await walk(db_client, account, run["id"])
    state = await read(db_client, account, run["id"])
    assert marked == state["blocks_total"] + state["objects_total"]
    assert state["complete"] is True

    empty = (await db_client.get(f"/review-runs/{run['id']}/next", headers=account.headers)).json()
    assert empty == {"block": None, "object": None}


@requires_database
async def test_open_critical_holds_technical_and_final(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")
    await walk(db_client, account, run["id"])

    issue = await registered(db_client, account, rows[0], severity="critical")

    refused = await db_client.post(f"/review-runs/{run['id']}/complete", headers=account.headers)
    assert refused.status_code == 409
    assert "критичных 1" in refused.json()["detail"]

    await act(db_client, account, issue["id"], "reject", note="Не ошибка")

    allowed = await db_client.post(f"/review-runs/{run['id']}/complete", headers=account.headers)
    assert allowed.status_code == 200, allowed.text


@requires_database
async def test_completed_work_goes_stale_when_the_text_changes(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")
    done = await finish(db_client, account, run["id"])
    assert done["stale"] is False

    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block)
    await act(db_client, account, issue["id"], "confirm")
    await edit(db_client, account, issue["id"], block, "Клапан защищает насос.")

    state = await read(db_client, account, run["id"])
    assert state["stale"] is True

    listing = await db_client.get(f"/chapters/{chapter_id}/reviews", headers=account.headers)
    assert listing.json()["technical"]["stale"] is True


# ── литературная правка ──


async def literary(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, str, list[dict]]:
    chapter_id, rows = await translated(client, session, account)
    technical = await start(client, account, chapter_id, "technical")
    await finish(client, account, technical["id"])
    run = await start(client, account, chapter_id, "literary")

    return chapter_id, run["id"], rows


@requires_database
async def test_literary_edit_keeps_the_reason_and_the_draft(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, run_id, rows = await literary(db_client, session, account)
    block = row_of(rows, PARAGRAPH)

    edited = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={
            "block_id": block["id"],
            "base_revision_id": block["current"]["id"],
            "text": "Насос защищён предохранительным клапаном.",
            "reason": "calque",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["violations"] == []

    new, old = await history(db_client, account, block["id"])
    assert new["edit_reason"] == "calque"
    assert new["stage"] == "working"
    assert new["origin"] == "human"
    assert old["text"] == block["current"]["text"]

    audit = await session.scalar(
        select(AuditEvent).where(AuditEvent.kind == "review.literary_edit")
    )
    assert audit is not None
    assert audit.payload["reason"] == "calque"


@requires_database
async def test_literary_edit_cannot_silently_change_the_protected(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, run_id, rows = await literary(db_client, session, account)
    block = row_of(rows, RADIUS)
    payload = {
        "block_id": block["id"],
        "base_revision_id": block["current"]["id"],
        "text": "Радиус задан.",
        "reason": "style",
    }

    refused = await db_client.post(
        f"/review-runs/{run_id}/edit", headers=account.headers, json=payload
    )
    assert refused.status_code == 409
    assert "защищённое" in refused.json()["detail"]

    # Настаивать можно только с причиной.
    no_reason = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={**payload, "accept_violation": True},
    )
    assert no_reason.status_code == 400

    forced = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={**payload, "accept_violation": True, "note": "Формула перенесена в подпись"},
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["violations"]

    # Нарушение стало замечанием, и оно держит завершение следующей работы.
    stats = await db_client.get(f"/issues/stats?chapter_id={chapter_id}", headers=account.headers)
    assert stats.json()["open_major"] == 1

    issues = await db_client.get(f"/issues?chapter_id={chapter_id}", headers=account.headers)
    assert issues.json()["items"][0]["category"] == "technical"


@requires_database
async def test_literary_edit_conflicts_with_a_newer_text(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, run_id, rows = await literary(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    payload = {
        "block_id": block["id"],
        "base_revision_id": block["current"]["id"],
        "text": "Предохранительный клапан надёжно защищает насос.",
        "reason": "readability",
    }

    assert (
        await db_client.post(f"/review-runs/{run_id}/edit", headers=account.headers, json=payload)
    ).status_code == 200

    second = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={**payload, "text": "Предохранительный клапан защищает насос всегда."},
    )
    assert second.status_code == 409
    assert "другим редактором" in second.json()["detail"]


@requires_database
async def test_listing_is_not_edited_for_style(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, run_id, rows = await literary(db_client, session, account)
    listing = next(row for row in rows if row["kind"] == BlockKind.CODE.value)

    refused = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={
            "block_id": listing["id"],
            "base_revision_id": listing["current"]["id"],
            "text": "print('красиво')",
            "reason": "style",
        },
    )
    assert refused.status_code == 409


@requires_database
async def test_edit_is_only_in_literary_review(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")
    block = row_of(rows, PARAGRAPH)

    refused = await db_client.post(
        f"/review-runs/{run['id']}/edit",
        headers=account.headers,
        json={
            "block_id": block["id"],
            "base_revision_id": block["current"]["id"],
            "text": "Правка.",
            "reason": "style",
        },
    )
    assert refused.status_code == 409


@requires_database
async def test_finished_literary_review_starts_the_rules_again(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, run_id, rows = await literary(db_client, session, account)
    block = row_of(rows, PARAGRAPH)

    edited = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={
            "block_id": block["id"],
            "base_revision_id": block["current"]["id"],
            "text": "Насос защищён предохранительным клапаном.",
            "reason": "style",
        },
    )
    assert edited.status_code == 200, edited.text
    await finish(db_client, account, run_id)

    state = (await db_client.get(f"/chapters/{chapter_id}/qa", headers=account.headers)).json()
    assert state["live"] is not None
    assert state["live"]["kind"] == "deterministic"


@requires_database
async def test_preview_warns_without_saving(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, run_id, rows = await literary(db_client, session, account)
    block = row_of(rows, RADIUS)

    preview = await db_client.post(
        f"/review-runs/{run_id}/edit/preview",
        headers=account.headers,
        json={
            "block_id": block["id"],
            "base_revision_id": block["current"]["id"],
            "text": "Радиус задан.",
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["violations"]

    new, *_ = await history(db_client, account, block["id"])
    assert new["id"] == block["current"]["id"]


@requires_database
async def test_preview_is_only_for_literary_review(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")
    block = row_of(rows, PARAGRAPH)

    refused = await db_client.post(
        f"/review-runs/{run['id']}/edit/preview",
        headers=account.headers,
        json={
            "block_id": block["id"],
            "base_revision_id": block["current"]["id"],
            "text": "Правка.",
        },
    )
    assert refused.status_code == 409


@requires_database
async def test_literary_edit_links_the_issue_of_this_block_only(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, run_id, rows = await literary(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    other = row_of(rows, RADIUS)
    foreign = await registered(db_client, account, other)
    own = await registered(db_client, account, block)
    payload = {
        "block_id": block["id"],
        "base_revision_id": block["current"]["id"],
        "text": "Насос защищён предохранительным клапаном.",
        "reason": "calque",
    }

    refused = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={**payload, "issue_id": foreign["id"]},
    )
    assert refused.status_code == 404

    saved = await db_client.post(
        f"/review-runs/{run_id}/edit",
        headers=account.headers,
        json={**payload, "issue_id": own["id"]},
    )
    assert saved.status_code == 200, saved.text

    new, *_ = await history(db_client, account, block["id"])
    assert new["issue_id"] == own["id"]


@requires_database
async def test_next_shows_open_issues_and_linked_objects(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")
    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block)

    after = block["ordinal"] - 1
    found = (
        await db_client.get(f"/review-runs/{run['id']}/next?after={after}", headers=account.headers)
    ).json()["block"]
    assert found["id"] == block["id"]
    assert [row["id"] for row in found["issues"]] == [issue["id"]]

    # Ячейка таблицы стоит в объекте: это видно рядом с её текстом.
    cell = row_of(rows, "Pressure")
    after = cell["ordinal"] - 1
    beside = (
        await db_client.get(f"/review-runs/{run['id']}/next?after={after}", headers=account.headers)
    ).json()["block"]
    assert beside["id"] == cell["id"]
    assert [(row["relation"], row["type"]) for row in beside["objects"]] == [("content", "table")]


@requires_database
async def test_skipped_object_comes_back(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")

    for row in rows:
        marked = await db_client.post(
            f"/review-runs/{run['id']}/blocks",
            headers=account.headers,
            json={"block_id": row["id"], "revision_id": row["current"]["id"]},
        )
        assert marked.status_code == 200, marked.text

    first = (await db_client.get(f"/review-runs/{run['id']}/next", headers=account.headers)).json()
    assert first["block"] is None
    item = first["object"]
    assert item["source_text"]
    assert item["translation"] is not None

    # Пропустили последний: очередь начинается сначала, а не заканчивается молча.
    total = (await read(db_client, account, run["id"]))["objects_total"]
    again = (
        await db_client.get(
            f"/review-runs/{run['id']}/next?after_object={total}", headers=account.headers
        )
    ).json()
    assert again["object"]["id"] == item["id"]


# ── финальная сверка и остальное ──


@requires_database
async def test_approved_text_is_not_overwritten_by_regression_without_a_decision(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)

    for kind in ("technical", "literary"):
        run = await start(db_client, account, chapter_id, kind)
        await finish(db_client, account, run["id"])
        if kind == "literary":
            assert await once(session, "test", STOP) is True

    final = await start(db_client, account, chapter_id, "final_compare")
    await finish(db_client, account, final["id"])

    repeated = [row for row in rows if row["source_text"].startswith("Check")]
    issue = await registered(db_client, account, repeated[0])
    await act(db_client, account, issue["id"], "confirm")
    await edit(db_client, account, issue["id"], repeated[0], "Проверяйте клапан.")

    run = await regression(db_client, account, issue["id"])
    twin = next(item for item in run["items"] if item["block_id"] == repeated[1]["id"])
    assert twin["final_candidate"] is True

    refused = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [twin["id"]]},
    )
    assert refused.status_code == 409


@requires_database
async def test_roles_and_isolation(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    chapter_id, _ = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")

    invited = await invite(db_client, account, role="translator")
    translator = await accept_as_new(db_client, token_of(invited))

    refused = await db_client.post(
        f"/chapters/{chapter_id}/reviews", headers=translator, json={"kind": "final_compare"}
    )
    assert refused.status_code == 403

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    assert (
        await db_client.get(f"/review-runs/{run['id']}", headers=stranger.headers)
    ).status_code == 404
    assert (
        await db_client.get(f"/chapters/{chapter_id}/reviews", headers=stranger.headers)
    ).status_code == 404
    assert (
        await db_client.post(f"/review-runs/{run['id']}/complete", headers=stranger.headers)
    ).status_code == 404


@requires_database
async def test_issue_mark_needs_a_real_issue(db_client: AsyncClient, session: AsyncSession) -> None:
    """«Посмотрели и завели замечание» без замечания засчитало бы место, ничего не сказав."""
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")
    block = row_of(rows, PARAGRAPH)
    mark = {"block_id": block["id"], "revision_id": block["current"]["id"], "result": "issue"}

    refused = await db_client.post(
        f"/review-runs/{run['id']}/blocks", headers=account.headers, json=mark
    )
    assert refused.status_code == 409
    assert "замечание" in refused.json()["detail"]

    issue = await registered(db_client, account, block)
    accepted = await db_client.post(
        f"/review-runs/{run['id']}/blocks", headers=account.headers, json=mark
    )
    assert accepted.status_code == 200, accepted.text
    assert issue["id"]


@requires_database
async def test_no_bulk_mark_exists(db_client: AsyncClient, session: AsyncSession) -> None:
    """Отметка «сверено» ставится по одному месту: кнопки «принять всё» нет и в API."""
    account = await register(db_client)
    chapter_id, rows = await translated(db_client, session, account)
    run = await start(db_client, account, chapter_id, "technical")

    refused = await db_client.post(
        f"/review-runs/{run['id']}/blocks",
        headers=account.headers,
        json={"block_ids": [row["id"] for row in rows]},
    )
    assert refused.status_code == 422
