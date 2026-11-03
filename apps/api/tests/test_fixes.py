"""Исправление по замечанию и регрессия: правка не затирает и не расходится сама."""

import uuid
from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.memory import TranslationUnit
from app.models.translation import RevisionOrigin, RevisionStage, TranslationRevision
from app.services.memory import fingerprint
from tests.conftest import requires_database
from tests.factories import Account, register
from tests.test_chapter_translation import Scripted, blocks, history, ready, scripted, translate
from tests.test_issues import act, read, registered

__all__ = ["scripted"]

REPEATED = "Check the relief valve daily."
PARAGRAPH = "The relief valve protects the pump."


async def translated(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, list[dict], list[dict]]:
    _, chapters = await ready(client, account)
    chapter_id = chapters[0]["id"]
    await translate(client, session, account, chapter_id)

    return chapter_id, chapters, await blocks(client, account, chapter_id)


def row_of(rows: list[dict], text_value: str) -> dict:
    return next(row for row in rows if row["source_text"] == text_value)


async def confirmed(client: AsyncClient, account: Account, block: dict, **extra: object) -> dict:
    issue = await registered(client, account, block, **extra)
    await act(client, account, issue["id"], "confirm")

    return issue


async def edit(
    client: AsyncClient,
    account: Account,
    issue_id: str,
    block: dict,
    text_value: str = "Исправленный текст",
    *,
    base: str | None = None,
    expect: int = 200,
) -> dict:
    return await act(
        client,
        account,
        issue_id,
        "revision",
        expect=expect,
        block_id=block["id"],
        base_revision_id=base or block["current"]["id"],
        text=text_value,
    )


async def regression(client: AsyncClient, account: Account, issue_id: str) -> dict:
    response = await client.get(f"/issues/{issue_id}/regression", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


async def settle(client: AsyncClient, account: Account, run: dict) -> None:
    """Решить все обязательные места как незатронутые."""
    for item in run["items"]:
        if item["required"] and item["decision"] == "pending":
            answer = await client.post(
                f"/regression-items/{item['id']}/decision",
                headers=account.headers,
                json={"affected": False},
            )
            assert answer.status_code == 200, answer.text


# ── правка ──


@requires_database
async def test_fix_makes_a_new_revision_and_keeps_the_draft(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    draft = block["current"]["text"]
    issue = await confirmed(db_client, account, block)

    fixed = await edit(db_client, account, issue["id"], block, "Клапан защищает насос.")
    assert fixed["status"] == "fixed"

    entries = await history(db_client, account, block["id"])
    new, old = entries
    assert new["text"] == "Клапан защищает насос."
    assert new["stage"] == "working"
    assert new["origin"] == "human"
    assert new["current"] is True
    assert new["supersedes_id"] == old["id"]
    assert old["text"] == draft
    assert old["stage"] == "draft"

    detail = await read(db_client, account, issue["id"])
    assert detail["fix_revision_id"] == new["id"]
    assert detail["events"][-1]["to_status"] == "fixed"
    assert detail["events"][-1]["related_revision_id"] == new["id"]
    # Снимок того, что нашли, не изменился.
    assert detail["target_snapshot"] == draft


@requires_database
async def test_second_editor_gets_a_conflict_not_an_overwrite(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    first = await confirmed(db_client, account, block)
    second = await confirmed(db_client, account, block)
    seen = block["current"]["id"]

    await edit(db_client, account, first["id"], block, "Первая правка.", base=seen)

    refused = await db_client.post(
        f"/issues/{second['id']}/revision",
        headers=account.headers,
        json={"block_id": block["id"], "base_revision_id": seen, "text": "Вторая правка."},
    )
    assert refused.status_code == 409
    assert "другим редактором" in refused.json()["detail"]

    entries = await history(db_client, account, block["id"])
    assert entries[0]["text"] == "Первая правка."
    assert len(entries) == 2


@requires_database
async def test_two_editors_of_one_issue_are_told_what_happened(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await confirmed(db_client, account, block)
    seen = block["current"]["id"]

    await edit(db_client, account, issue["id"], block, "Первая правка.", base=seen)

    refused = await db_client.post(
        f"/issues/{issue['id']}/revision",
        headers=account.headers,
        json={"block_id": block["id"], "base_revision_id": seen, "text": "Вторая правка."},
    )

    assert refused.status_code == 409
    assert "другой редактор" in refused.json()["detail"]
    assert "fixed" not in refused.json()["detail"]


@requires_database
async def test_edit_is_only_for_a_confirmed_issue(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block)

    await edit(db_client, account, issue["id"], block, expect=409)

    await act(db_client, account, issue["id"], "reject", note="Не ошибка")
    await edit(db_client, account, issue["id"], block, expect=409)


@requires_database
async def test_edit_refuses_what_it_should_not_write(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    other = row_of(rows, "1 Pumps")
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "   ", expect=400)
    await edit(db_client, account, issue["id"], block, "Текст ⟦1⟧.", expect=400)
    await edit(db_client, account, issue["id"], block, block["current"]["text"], expect=400)
    # Чужой блок.
    await edit(db_client, account, issue["id"], other, expect=409)


@requires_database
async def test_listing_cannot_be_edited(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    listing = next(row for row in rows if row["kind"] == "code")
    issue = await confirmed(db_client, account, listing)

    await edit(db_client, account, issue["id"], listing, "print('x')", expect=409)

    detail = await read(db_client, account, issue["id"])
    assert detail["editable"] == []


@requires_database
async def test_editable_shows_what_stands_now(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await confirmed(db_client, account, block)

    [item] = (await read(db_client, account, issue["id"]))["editable"]

    assert item["block_id"] == block["id"]
    assert item["revision_id"] == block["current"]["id"]
    assert item["text"] == block["current"]["text"]


# ── регрессия ──


@requires_database
async def test_fix_opens_regression_and_nothing_spreads_by_itself(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    chapter_id, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    twin = [row for row in rows if row["source_text"] == REPEATED and row["id"] != block["id"]][0]
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Проверяйте клапан каждый день.")

    run = await regression(db_client, account, issue["id"])
    assert run["status"] == "open"
    kinds = {item["kind"] for item in run["items"]}
    assert "same_source_repeat" in kinds
    assert "adjacent_context" in kinds

    repeat = next(item for item in run["items"] if item["block_id"] == twin["id"])
    assert repeat["kind"] == "same_source_repeat"
    assert repeat["required"] is True
    assert repeat["safe"] is True
    assert repeat["proposed_text"] == "Проверяйте клапан каждый день."

    # Сам повтор не изменился.
    after = next(
        row for row in await blocks(db_client, account, chapter_id) if row["id"] == twin["id"]
    )
    assert after["current"]["id"] == twin["current"]["id"]

    adjacent = [item for item in run["items"] if item["kind"] == "adjacent_context"]
    assert adjacent
    assert all(item["required"] is False for item in adjacent)


@requires_database
async def test_cannot_close_until_regression_is_finished(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")
    await act(db_client, account, issue["id"], "verification")

    refused = await db_client.post(f"/issues/{issue['id']}/close", headers=account.headers, json={})
    assert refused.status_code == 409
    assert "регрессию" in refused.json()["detail"]

    await settle(db_client, account, await regression(db_client, account, issue["id"]))

    run = await regression(db_client, account, issue["id"])
    assert run["status"] == "completed"
    assert run["pending"] == 0

    assert (await act(db_client, account, issue["id"], "close"))["status"] == "closed"


@requires_database
async def test_apply_selected_gives_each_repeat_its_own_revision(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")
    run = await regression(db_client, account, issue["id"])
    repeat = next(
        item
        for item in run["items"]
        if item["kind"] == "same_source_repeat" and item["current_text"] is not None
    )

    applied = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [repeat["id"]]},
    )
    assert applied.status_code == 200, applied.text

    entries = await history(db_client, account, repeat["block_id"])
    assert entries[0]["text"] == "Проверяйте клапан."
    assert entries[0]["stage"] == "working"
    assert entries[0]["origin"] == "human"
    assert entries[0]["current"] is True

    after = await regression(db_client, account, issue["id"])
    done = next(item for item in after["items"] if item["id"] == repeat["id"])
    assert done["decision"] == "propagated"

    # Второй раз то же решение не принимается.
    again = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [repeat["id"]]},
    )
    assert again.status_code == 409


@requires_database
async def test_apply_is_all_or_nothing_when_a_text_has_moved_on(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    chapter_id, chapters, _ = await translated(db_client, session, account)
    await translate(db_client, session, account, chapters[1]["id"])
    rows = await blocks(db_client, account, chapter_id)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")
    run = await regression(db_client, account, issue["id"])
    repeats = [item for item in run["items"] if item["kind"] == "same_source_repeat"]
    assert len(repeats) == 2

    # Один из повторов успел измениться после расчёта.
    moved = repeats[0]
    other_issue = await confirmed(
        db_client, account, {"id": moved["block_id"]}, description="Своя ошибка"
    )
    await act(
        db_client,
        account,
        other_issue["id"],
        "revision",
        block_id=moved["block_id"],
        base_revision_id=(await history(db_client, account, moved["block_id"]))[0]["id"],
        text="Другой текст.",
    )

    refused = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [item["id"] for item in repeats]},
    )
    assert refused.status_code == 409

    # Второй повтор тоже не тронут.
    untouched = await history(db_client, account, repeats[1]["block_id"])
    assert len(untouched) == 1


@requires_database
async def test_repeat_with_a_different_text_is_not_safe(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    twin = [row for row in rows if row["source_text"] == REPEATED and row["id"] != block["id"]][0]

    earlier = await confirmed(db_client, account, twin)
    await edit(db_client, account, earlier["id"], twin, "Уже другой перевод.")

    issue = await confirmed(db_client, account, block)
    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")

    run = await regression(db_client, account, issue["id"])
    repeat = next(item for item in run["items"] if item["block_id"] == twin["id"])

    assert repeat["safe"] is False
    assert repeat["current_text"] == "Уже другой перевод."


@requires_database
async def test_final_candidate_is_not_overwritten_without_a_separate_decision(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    twin = [row for row in rows if row["source_text"] == REPEATED and row["id"] != block["id"]][0]

    # В повторе уже стоит кандидат в финальный текст: редакции неизменяемы, поэтому новая строка.
    final = TranslationRevision(
        id=uuid.uuid4(),
        organization_id=account.organization_id,
        block_id=uuid.UUID(twin["id"]),
        revision_no=2,
        stage=RevisionStage.FINAL_CANDIDATE,
        origin=RevisionOrigin.HUMAN,
        text="Кандидат в финальный текст.",
        supersedes_id=uuid.UUID(twin["current"]["id"]),
    )
    session.add(final)
    await session.flush()
    stored = await session.get(Block, uuid.UUID(twin["id"]))
    assert stored is not None
    stored.current_revision_id = final.id
    await session.flush()

    issue = await confirmed(db_client, account, block)
    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")
    run = await regression(db_client, account, issue["id"])
    repeat = next(item for item in run["items"] if item["block_id"] == twin["id"])
    assert repeat["final_candidate"] is True

    refused = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [repeat["id"]]},
    )
    assert refused.status_code == 409
    assert "кандидат" in refused.json()["detail"]

    no_reason = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [repeat["id"]], "overwrite_final": True},
    )
    assert no_reason.status_code == 400

    allowed = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=account.headers,
        json={"item_ids": [repeat["id"]], "overwrite_final": True, "note": "Ошибка в кандидате"},
    )
    assert allowed.status_code == 200, allowed.text

    entries = await history(db_client, account, twin["id"])
    assert entries[0]["text"] == "Проверяйте клапан."
    # Кандидат никуда не делся: он остался в истории.
    assert entries[1]["text"] == "Кандидат в финальный текст."


@requires_database
async def test_affected_place_gets_a_child_issue_that_holds_the_parent(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")
    await act(db_client, account, issue["id"], "verification")

    run = await regression(db_client, account, issue["id"])
    repeat = next(item for item in run["items"] if item["kind"] == "same_source_repeat")

    incomplete = await db_client.post(
        f"/regression-items/{repeat['id']}/decision",
        headers=account.headers,
        json={"affected": True},
    )
    assert incomplete.status_code == 400

    decided = await db_client.post(
        f"/regression-items/{repeat['id']}/decision",
        headers=account.headers,
        json={
            "affected": True,
            "note": "Здесь контекст другой",
            "category": "semantic",
            "severity": "major",
        },
    )
    assert decided.status_code == 200, decided.text

    item = next(row for row in decided.json()["items"] if row["id"] == repeat["id"])
    assert item["decision"] == "issue_created"
    # Код дочернего — по главе его блока: повтор мог стоять и в другой главе.
    assert item["child_code"].startswith("BK01-CH")
    assert "-ERR-" in item["child_code"]

    await settle(db_client, account, await regression(db_client, account, issue["id"]))

    # Регрессия завершена, но дочернее замечание ещё открыто.
    refused = await db_client.post(f"/issues/{issue['id']}/close", headers=account.headers, json={})
    assert refused.status_code == 409
    assert item["child_code"] in refused.json()["detail"]

    await act(db_client, account, item["child_issue_id"], "reject", note="Не ошибка")
    assert (await act(db_client, account, issue["id"], "close"))["status"] == "closed"


@requires_database
async def test_reopened_issue_gets_a_new_regression_for_the_new_fix(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Первая правка.")
    old = await regression(db_client, account, issue["id"])

    await act(db_client, account, issue["id"], "reopen", note="Плохо исправлено")
    await act(db_client, account, issue["id"], "confirm")

    stale = await db_client.post(
        f"/regression-items/{old['items'][0]['id']}/decision",
        headers=account.headers,
        json={"affected": False},
    )
    assert stale.status_code == 409

    current = (await read(db_client, account, issue["id"]))["editable"][0]
    await act(
        db_client,
        account,
        issue["id"],
        "revision",
        block_id=block["id"],
        base_revision_id=current["revision_id"],
        text="Вторая правка.",
    )

    fresh = await regression(db_client, account, issue["id"])
    assert fresh["id"] != old["id"]
    assert fresh["status"] == "open"


@requires_database
async def test_viewer_and_stranger_cannot_touch_regression(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = next(row for row in rows if row["source_text"] == REPEATED)
    issue = await confirmed(db_client, account, block)
    await edit(db_client, account, issue["id"], block, "Проверяйте клапан.")
    run = await regression(db_client, account, issue["id"])

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    seen = await db_client.get(f"/issues/{issue['id']}/regression", headers=stranger.headers)
    assert seen.status_code == 404

    applied = await db_client.post(
        f"/regression-runs/{run['id']}/apply",
        headers=stranger.headers,
        json={"item_ids": [run["items"][0]["id"]]},
    )
    assert applied.status_code == 404

    decided = await db_client.post(
        f"/regression-items/{run['items'][0]['id']}/decision",
        headers=stranger.headers,
        json={"affected": False},
    )
    assert decided.status_code == 404


# ── память переводов ──


async def memory_size(client: AsyncClient, account: Account) -> int:
    response = await client.get("/memory", headers=account.headers)
    assert response.status_code == 200, response.text

    return int(response.json()["total"])


@requires_database
async def test_fix_reaches_memory_only_after_verification(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await confirmed(db_client, account, block)

    await edit(db_client, account, issue["id"], block, "Клапан защищает насос.")
    assert await memory_size(db_client, account) == 0

    await act(db_client, account, issue["id"], "verification")

    listing = await db_client.get("/memory", headers=account.headers)
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["target_text"] == "Клапан защищает насос."


@requires_database
async def test_memory_policy_can_wait_for_closing(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await confirmed(db_client, account, block)

    saved = await db_client.put(
        "/settings/workspace", headers=account.headers, json={"memory_publish_on": "closed"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["memory_publish_on"] == "closed"

    await edit(db_client, account, issue["id"], block, "Клапан защищает насос.")
    await act(db_client, account, issue["id"], "verification")
    assert await memory_size(db_client, account) == 0

    await settle(db_client, account, await regression(db_client, account, issue["id"]))
    await act(db_client, account, issue["id"], "close")
    assert await memory_size(db_client, account) == 1


async def origin_in_a_new_book(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, str]:
    """Перевести такой же текст в новой книге: повтор внутри книги здесь не сработает."""
    _, chapters = await ready(client, account)
    await translate(client, session, account, chapters[0]["id"])
    row = row_of(await blocks(client, account, chapters[0]["id"]), PARAGRAPH)

    return row["current"]["origin"], row["current"]["text"]


@requires_database
async def test_verified_fix_serves_the_next_book(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await confirmed(db_client, account, block)
    fixed = "Предохранительный клапан защищает насос."

    await edit(db_client, account, issue["id"], block, fixed)
    await act(db_client, account, issue["id"], "verification")

    assert await origin_in_a_new_book(db_client, session, account) == ("memory", fixed)


@requires_database
async def test_verified_memory_that_breaks_the_glossary_is_not_used(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = row_of(rows, PARAGRAPH)
    issue = await confirmed(db_client, account, block)

    # В утверждённом глоссарии термин обязателен, а в этом переводе его нет.
    await edit(db_client, account, issue["id"], block, "Вентиль защищает насос.")
    await act(db_client, account, issue["id"], "verification")
    assert await memory_size(db_client, account) == 1

    origin, _ = await origin_in_a_new_book(db_client, session, account)
    assert origin == "model"


@requires_database
async def test_unverified_memory_does_not_reach_the_text(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    session.add(
        TranslationUnit(
            organization_id=account.organization_id,
            source_language="en",
            target_language="ru",
            source_hash=fingerprint(PARAGRAPH),
            source_text=PARAGRAPH,
            target_text="Предохранительный клапан защищает насос (непроверенный).",
            origin="machine",
            verified=False,
        )
    )
    await session.flush()

    origin, text_value = await origin_in_a_new_book(db_client, session, account)

    assert origin == "model"
    assert "непроверенный" not in text_value
