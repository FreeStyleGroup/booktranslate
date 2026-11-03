"""Реестр ошибок: постоянные коды, снимки, жизненный цикл, правило двух человек."""

import csv
import io
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.issue import IssueCategory, IssueSeverity
from app.models.organization import Role, User
from app.services.context import RequestContext
from app.services.issue_numbers import dedupe_key
from app.services.issues import IssueService
from app.services.storage import LocalStorage
from app.worker import once
from tests.conftest import requires_database
from tests.factories import Account, register
from tests.test_chapter_translation import (
    STOP,
    Scripted,
    blocks,
    history,
    ready,
    scripted,
    translate,
)
from tests.test_team import accept_as_new, invite, token_of

__all__ = ["scripted"]

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def translated(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, str, list[dict]]:
    book_id, chapters = await ready(client, account)
    chapter_id = chapters[0]["id"]
    await translate(client, session, account, chapter_id)

    return book_id, chapter_id, await blocks(client, account, chapter_id)


def paragraph(rows: list[dict]) -> dict:
    return next(row for row in rows if row["source_text"].startswith("The relief"))


async def registered(client: AsyncClient, account: Account, block: dict, **extra: object) -> dict:
    payload = {
        "block_id": block["id"],
        "category": "number",
        "severity": "major",
        "description": "Потеряно число",
        **extra,
    }
    response = await client.post("/issues", headers=account.headers, json=payload)
    assert response.status_code == 201, response.text

    body: dict = response.json()
    return body


async def act(
    client: AsyncClient,
    account: Account | dict[str, str],
    issue_id: str,
    action: str,
    expect: int = 200,
    **payload: object,
) -> dict:
    headers = account.headers if isinstance(account, Account) else account
    response = await client.post(f"/issues/{issue_id}/{action}", headers=headers, json=payload)
    assert response.status_code == expect, response.text

    body: dict = response.json()
    return body


async def read(client: AsyncClient, account: Account, issue_id: str) -> dict:
    response = await client.get(f"/issues/{issue_id}", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


async def new_revision(
    client: AsyncClient,
    session: AsyncSession,
    account: Account,
    chapter_id: str,
    block: dict,
    scripted_provider: Callable[..., Scripted],
    *,
    adopt: bool = True,
) -> str:
    """Перевести блок заново и сделать вариант текущим."""
    scripted_provider(lambda items: {key: f"{value} (правка)" for key, value in items.items()})

    fresh = next(
        row for row in await blocks(client, account, chapter_id) if row["id"] == block["id"]
    )
    asked = await client.post(
        f"/chapters/{chapter_id}/translation/retranslate",
        headers=account.headers,
        json={"items": [{"block_id": block["id"], "base_revision_id": fresh["current"]["id"]}]},
    )
    assert asked.status_code == 201, asked.text
    assert await once(session, "test", STOP) is True

    variant: str = (await history(client, account, block["id"]))[0]["id"]

    if adopt:
        adopted = await client.post(f"/revisions/{variant}/adopt", headers=account.headers)
        assert adopted.status_code == 200, adopted.text

    return variant


async def confirmed(client: AsyncClient, account: Account, block: dict, **extra: object) -> dict:
    issue = await registered(client, account, block, **extra)
    await act(client, account, issue["id"], "confirm")

    return issue


# ── коды ──


@requires_database
async def test_code_comes_from_the_server_and_numbers_are_not_reused(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)

    first = await registered(db_client, account, block)
    second = await registered(db_client, account, block)

    assert first["code"] == "BK01-CH01-ERR-0001"
    assert second["code"] == "BK01-CH01-ERR-0002"

    await act(db_client, account, first["id"], "reject", note="Это не ошибка")

    third = await registered(db_client, account, block)
    assert third["code"] == "BK01-CH01-ERR-0003"

    copied = await db_client.get(f"/issues?chapter_id={chapter_id}", headers=account.headers)
    assert copied.json()["total"] == 3


@requires_database
async def test_client_cannot_set_code_status_or_snapshots(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)

    for extra in (
        {"code": "BK99-CH99-ERR-9999"},
        {"status": "closed"},
        {"source_snapshot": "другое"},
        {"detected_by_id": str(uuid.uuid4())},
    ):
        response = await db_client.post(
            "/issues",
            headers=account.headers,
            json={
                "block_id": paragraph(rows)["id"],
                "category": "number",
                "severity": "major",
                "description": "Потеряно число",
                **extra,
            },
        )
        assert response.status_code == 422, extra


@requires_database
async def test_issue_needs_a_subject(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.post(
        "/issues",
        headers=account.headers,
        json={"category": "number", "severity": "major", "description": "Без привязки"},
    )

    assert response.status_code == 400


@requires_database
async def test_repeated_finding_of_a_check_gets_the_same_code(
    db_client: AsyncClient, session: AsyncSession, storage_root: Path
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)

    me = await session.get(User, account.user_id)
    assert me is not None
    context = RequestContext(user=me, organization_id=account.organization_id, role=Role.OWNER)
    service = IssueService(session, context, LocalStorage(storage_root))
    key = dedupe_key(
        "numbers",
        block_id=uuid.UUID(block["id"]),
        object_id=None,
        revision_id=uuid.UUID(block["current"]["id"]),
        finding="Число пропало",
    )

    first = await service.register(
        block_id=uuid.UUID(block["id"]),
        object_id=None,
        category=IssueCategory.NUMBER,
        severity=IssueSeverity.MAJOR,
        description="Число пропало",
        dedupe_key=key,
        automatic=True,
    )
    again = await service.register(
        block_id=uuid.UUID(block["id"]),
        object_id=None,
        category=IssueCategory.NUMBER,
        severity=IssueSeverity.MAJOR,
        description="Число пропало",
        dedupe_key=key,
        automatic=True,
    )

    assert again.id == first.id
    assert first.automatic is True
    assert first.detected_by_id is None


# ── снимки и неизменяемость ──


@requires_database
async def test_snapshot_stays_as_it_was_after_the_text_changes(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    before = block["current"]["text"]

    issue = await registered(db_client, account, block)
    assert issue["source_snapshot"] == block["source_text"]
    assert issue["target_snapshot"] == before
    assert issue["discovered_revision_id"] == block["current"]["id"]

    await new_revision(db_client, session, account, chapter_id, block, scripted)

    after = await read(db_client, account, issue["id"])
    assert after["target_snapshot"] == before
    assert after["current_text"] != before
    assert after["current_text"].endswith("(правка)")


@requires_database
async def test_database_itself_refuses_to_rewrite_or_delete_a_finding(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))
    issue_id = issue["id"]
    event_id = issue["events"][0]["id"]

    for statement in (
        "UPDATE issues SET target_snapshot = 'другое' WHERE id = :id",
        "UPDATE issues SET description = 'другое' WHERE id = :id",
        "UPDATE issues SET code = 'BK99' WHERE id = :id",
        "DELETE FROM issues WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="restrict_violation|не меняет|не удаляются"):
            async with session.begin_nested():
                await session.execute(text(statement), {"id": issue_id})

    for statement in (
        "UPDATE issue_events SET note = 'другое' WHERE id = :id",
        "DELETE FROM issue_events WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="restrict_violation|неизменяемо|не удаляются"):
            async with session.begin_nested():
                await session.execute(text(statement), {"id": event_id})


@requires_database
async def test_organization_removal_still_takes_its_registry_along(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Запрет на прямое удаление не должен держать данные ушедшего клиента вечно."""
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    await registered(db_client, account, paragraph(rows))

    async with session.begin_nested():
        await session.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": account.organization_id}
        )
        # Внешние ключи реестра отложены: проверяем их здесь, а не при фиксации, которой в
        # тесте не будет.
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    left = await session.scalar(
        text("SELECT count(*) FROM issues WHERE organization_id = :id"),
        {"id": account.organization_id},
    )
    assert left == 0


@requires_database
async def test_no_way_to_patch_or_delete_through_api(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))

    patched = await db_client.patch(
        f"/issues/{issue['id']}", headers=account.headers, json={"status": "closed"}
    )
    deleted = await db_client.delete(f"/issues/{issue['id']}", headers=account.headers)

    assert patched.status_code == 405
    assert deleted.status_code == 405


@requires_database
async def test_project_with_registered_issues_is_not_deleted(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, _, rows = await translated(db_client, session, account)
    await registered(db_client, account, paragraph(rows))

    book = await db_client.get(f"/books/{book_id}", headers=account.headers)
    removed = await db_client.delete(
        f"/projects/{book.json()['project_id']}", headers=account.headers
    )

    assert removed.status_code == 409
    assert "ошибки" in removed.json()["detail"]


# ── жизненный цикл ──


@requires_database
async def test_new_cannot_jump_over_confirmation_or_verification(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await registered(db_client, account, block)

    await act(
        db_client, account, issue["id"], "fix", expect=409, revision_id=block["current"]["id"]
    )
    await act(db_client, account, issue["id"], "close", expect=409)
    await act(db_client, account, issue["id"], "verification", expect=409)
    await act(db_client, account, issue["id"], "clarification/answer", expect=409, note="Ответ")


@requires_database
async def test_reject_and_clarification_need_a_comment_and_change_nothing_in_the_text(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await registered(db_client, account, block)

    await act(db_client, account, issue["id"], "reject", expect=422)
    await act(db_client, account, issue["id"], "reject", expect=400, note="   ")
    await act(db_client, account, issue["id"], "clarification", expect=422)

    rejected = await act(db_client, account, issue["id"], "reject", note="Это не ошибка")
    assert rejected["status"] == "rejected"

    # Отклонённое остаётся в реестре и истории, а перевод тот же.
    listing = await db_client.get(f"/issues?chapter_id={chapter_id}", headers=account.headers)
    assert [item["id"] for item in listing.json()["items"]] == [issue["id"]]

    detail = await read(db_client, account, issue["id"])
    assert [event["to_status"] for event in detail["events"]] == ["new", "rejected"]
    assert detail["events"][1]["note"] == "Это не ошибка"

    after = next(
        row for row in await blocks(db_client, account, chapter_id) if row["id"] == block["id"]
    )
    assert after["current"]["id"] == block["current"]["id"]


@requires_database
async def test_clarification_returns_through_reopened_with_the_current_revision(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await registered(db_client, account, block)

    asked = await act(db_client, account, issue["id"], "clarification", note="Какое число?")
    assert asked["status"] == "needs_clarification"

    await act(db_client, account, issue["id"], "confirm", expect=409)

    answered = await act(db_client, account, issue["id"], "clarification/answer", note="12,5")
    assert answered["status"] == "reopened"

    detail = await read(db_client, account, issue["id"])
    assert detail["events"][-1]["note"] == "12,5"
    assert detail["events"][-1]["related_revision_id"] == block["current"]["id"]

    assert (await act(db_client, account, issue["id"], "confirm"))["status"] == "confirmed"


@requires_database
async def test_fix_needs_a_new_current_revision_of_the_same_block(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    other = next(row for row in rows if row["source_text"] == "1 Pumps")
    issue = await confirmed(db_client, account, block)

    # Та самая редакция, на которую поставлено замечание, ничего не исправляет.
    await act(
        db_client, account, issue["id"], "fix", expect=409, revision_id=block["current"]["id"]
    )
    # Чужой блок.
    await act(
        db_client, account, issue["id"], "fix", expect=409, revision_id=other["current"]["id"]
    )
    # Несуществующая.
    await act(db_client, account, issue["id"], "fix", expect=404, revision_id=str(uuid.uuid4()))

    variant = await new_revision(
        db_client, session, account, chapter_id, block, scripted, adopt=False
    )
    # Вариант, которого читатель не увидит: он ещё не текущий.
    await act(db_client, account, issue["id"], "fix", expect=409, revision_id=variant)

    candidates = (await read(db_client, account, issue["id"]))["candidates"]
    assert candidates == []

    adopted = await db_client.post(f"/revisions/{variant}/adopt", headers=account.headers)
    assert adopted.status_code == 200, adopted.text

    candidates = (await read(db_client, account, issue["id"]))["candidates"]
    assert [item["revision_id"] for item in candidates] == [variant]

    fixed = await act(db_client, account, issue["id"], "fix", revision_id=variant)
    assert fixed["status"] == "fixed"

    detail = await read(db_client, account, issue["id"])
    assert detail["fix_revision_id"] == variant
    assert detail["events"][-1]["related_revision_id"] == variant


@requires_database
async def test_verification_checks_the_text_that_stands_now(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await confirmed(db_client, account, block)

    fix = await new_revision(db_client, session, account, chapter_id, block, scripted)
    await act(db_client, account, issue["id"], "fix", revision_id=fix)

    # После исправления текст сменился: проверять уже нечего.
    await new_revision(db_client, session, account, chapter_id, block, scripted)
    await act(db_client, account, issue["id"], "verification", expect=409)

    reopened = await act(db_client, account, issue["id"], "reopen", note="Текст сменился")
    assert reopened["status"] == "reopened"

    detail = await read(db_client, account, issue["id"])
    assert detail["fix_revision_id"] is None
    assert detail["events"][-1]["related_revision_id"] == detail["current_revision_id"]


@requires_database
async def test_full_path_to_closed_and_back(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await confirmed(db_client, account, block)

    fix = await new_revision(db_client, session, account, chapter_id, block, scripted)
    await act(db_client, account, issue["id"], "fix", revision_id=fix)
    await act(db_client, account, issue["id"], "verification", note="Сверено")
    closed = await act(db_client, account, issue["id"], "close")
    assert closed["status"] == "closed"

    detail = await read(db_client, account, issue["id"])
    assert [event["to_status"] for event in detail["events"]] == [
        "new",
        "confirmed",
        "fixed",
        "verified",
        "closed",
    ]
    assert detail["actions"] == ["comment", "reopen", "archive"]

    await act(db_client, account, issue["id"], "reopen", expect=422)
    assert (await act(db_client, account, issue["id"], "reopen", note="Снова"))["status"] == (
        "reopened"
    )


@requires_database
async def test_parent_does_not_close_while_a_child_is_open(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    parent = await confirmed(db_client, account, block)

    fix = await new_revision(db_client, session, account, chapter_id, block, scripted)
    await act(db_client, account, parent["id"], "fix", revision_id=fix)
    await act(db_client, account, parent["id"], "verification")

    child = await registered(db_client, account, block, parent_issue_id=parent["id"])

    refused = await db_client.post(
        f"/issues/{parent['id']}/close", headers=account.headers, json={}
    )
    assert refused.status_code == 409
    assert child["code"] in refused.json()["detail"]

    await act(db_client, account, child["id"], "reject", note="Не регрессия")
    assert (await act(db_client, account, parent["id"], "close"))["status"] == "closed"

    detail = await read(db_client, account, parent["id"])
    assert [item["code"] for item in detail["children"]] == [child["code"]]


# ── классификация ──


@requires_database
async def test_reclassification_needs_a_reason_and_stays_in_the_timeline(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))
    before = issue["priority_score"]

    await act(db_client, account, issue["id"], "classification", expect=422, severity="critical")
    await act(db_client, account, issue["id"], "classification", expect=400, reason="Без изменений")

    changed = await act(
        db_client,
        account,
        issue["id"],
        "classification",
        reason="Неверное давление опасно",
        severity="critical",
        category="semantic",
    )
    assert changed["severity"] == "critical"
    assert changed["priority_score"] > before

    event = (await read(db_client, account, issue["id"]))["events"][-1]
    assert event["kind"] == "reclassified"
    assert event["note"] == "Неверное давление опасно"
    assert event["payload"]["severity"] == ["major", "critical"]
    assert event["payload"]["category"] == ["number", "semantic"]

    audit = await session.scalar(select(AuditEvent).where(AuditEvent.kind == "issue.reclassified"))
    assert audit is not None

    await act(db_client, account, issue["id"], "reject", note="Не ошибка")
    await act(
        db_client,
        account,
        issue["id"],
        "classification",
        expect=409,
        reason="Поздно",
        severity="minor",
    )


# ── правило двух человек ──


async def reviewer_of(client: AsyncClient, owner: Account) -> dict[str, str]:
    invited = await invite(client, owner, role="reviewer")

    return await accept_as_new(client, token_of(invited))


@requires_database
async def test_two_person_rule_is_off_by_default_and_binds_only_critical(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)

    critical = await registered(db_client, account, block, severity="critical")
    assert (await act(db_client, account, critical["id"], "confirm"))["status"] == "confirmed"

    switched = await db_client.put(
        "/settings/workspace", headers=account.headers, json={"two_person_review": True}
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["two_person_review"] is True

    audit = await session.scalar(
        select(AuditEvent).where(AuditEvent.kind == "workspace.two_person_review")
    )
    assert audit is not None
    assert audit.payload == {"enabled": True}

    minor = await registered(db_client, account, block, severity="minor")
    assert (await act(db_client, account, minor["id"], "confirm"))["status"] == "confirmed"


@requires_database
async def test_two_person_rule_needs_another_person_for_critical(
    db_client: AsyncClient, session: AsyncSession, scripted: Callable[..., Scripted]
) -> None:
    scripted()
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    reviewer = await reviewer_of(db_client, account)

    await db_client.put(
        "/settings/workspace", headers=account.headers, json={"two_person_review": True}
    )

    issue = await registered(db_client, account, block, severity="critical")
    detail = await read(db_client, account, issue["id"])
    assert detail["review_note"] is not None

    await act(db_client, account, issue["id"], "confirm", expect=409)
    await act(db_client, account, issue["id"], "reject", expect=409, note="Своё")

    assert (await act(db_client, reviewer, issue["id"], "confirm"))["status"] == "confirmed"

    # Исправил владелец: проверить исправление он тоже не вправе.
    fix = await new_revision(db_client, session, account, chapter_id, block, scripted)
    await act(db_client, account, issue["id"], "fix", revision_id=fix)
    await act(db_client, account, issue["id"], "verification", expect=409)

    assert (await act(db_client, reviewer, issue["id"], "verification"))["status"] == "verified"


# ── права и изоляция ──


@requires_database
async def test_viewer_reads_but_does_not_act(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await registered(db_client, account, block)

    invited = await invite(db_client, account, role="viewer")
    viewer = await accept_as_new(db_client, token_of(invited))

    seen = await db_client.get(f"/issues/{issue['id']}", headers=viewer)
    assert seen.status_code == 200
    assert seen.json()["actions"] == []

    refused = await db_client.post(
        "/issues",
        headers=viewer,
        json={
            "block_id": block["id"],
            "category": "style",
            "severity": "minor",
            "description": "Нельзя",
        },
    )
    assert refused.status_code == 403

    await act(db_client, viewer, issue["id"], "confirm", expect=403)


@requires_database
async def test_translator_registers_but_does_not_decide(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await registered(db_client, account, block)

    invited = await invite(db_client, account, role="translator")
    translator = await accept_as_new(db_client, token_of(invited))

    assert (await db_client.get(f"/issues/{issue['id']}", headers=translator)).json()[
        "actions"
    ] == ["comment"]
    await act(db_client, translator, issue["id"], "confirm", expect=403)
    await act(db_client, translator, issue["id"], "comments", note="Посмотрите, пожалуйста")


@requires_database
async def test_other_workspace_sees_nothing(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)
    issue = await registered(db_client, account, block)

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    assert (
        await db_client.get(f"/issues/{issue['id']}", headers=stranger.headers)
    ).status_code == 404
    await act(db_client, stranger, issue["id"], "confirm", expect=404)

    listing = await db_client.get(f"/issues?chapter_id={chapter_id}", headers=stranger.headers)
    assert listing.json()["total"] == 0

    planted = await db_client.post(
        "/issues",
        headers=stranger.headers,
        json={
            "block_id": block["id"],
            "category": "style",
            "severity": "minor",
            "description": "На чужой блок",
        },
    )
    assert planted.status_code == 404

    found = await db_client.get(f"/search?query={issue['code']}", headers=stranger.headers)
    assert found.json()["issues"]["total"] == 0


@requires_database
async def test_assignee_must_be_a_member(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))
    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    await act(
        db_client, account, issue["id"], "assignee", expect=400, assignee_id=str(stranger.user_id)
    )

    assigned = await act(
        db_client, account, issue["id"], "assignee", assignee_id=str(account.user_id)
    )
    assert assigned["assignee"] == "owner@example.com"

    mine = await db_client.get(f"/issues?assignee_id={account.user_id}", headers=account.headers)
    assert mine.json()["total"] == 1


# ── объекты, контекст ──


@requires_database
async def test_issue_on_object_takes_its_blocks_into_the_snapshot(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapter_id, _ = await translated(db_client, session, account)

    masters = await db_client.get(f"/chapters/{chapter_id}/masters", headers=account.headers)
    objects = await db_client.get(
        f"/masters/{masters.json()[0]['id']}/objects", headers=account.headers
    )
    table = next(item for item in objects.json() if item["type"] == "table")

    response = await db_client.post(
        "/issues",
        headers=account.headers,
        json={
            "object_id": table["id"],
            "category": "table",
            "severity": "major",
            "description": "Сбита колонка",
        },
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["block_id"] is None
    assert body["object_code"] == "CH01-TBL001"
    assert "Pressure" in body["source_snapshot"]
    assert "12,5" in body["target_snapshot"]
    assert [item["code"] for item in body["objects"]] == ["CH01-TBL001"]
    # Риск таблицы поднимает вес выше такого же замечания на абзац.
    assert body["priority_score"] > 31


@requires_database
async def test_block_outside_the_object_is_refused(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    masters = await db_client.get(f"/chapters/{chapter_id}/masters", headers=account.headers)
    objects = await db_client.get(
        f"/masters/{masters.json()[0]['id']}/objects", headers=account.headers
    )
    table = next(item for item in objects.json() if item["type"] == "table")

    response = await db_client.post(
        "/issues",
        headers=account.headers,
        json={
            "block_id": paragraph(rows)["id"],
            "object_id": table["id"],
            "category": "table",
            "severity": "major",
            "description": "Не тот блок",
        },
    )

    assert response.status_code == 400


@requires_database
async def test_verifier_gets_context_and_terms(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)

    issue = await registered(db_client, account, paragraph(rows))

    assert [item["source_text"] for item in issue["context"]][:1] == ["1 Pumps"]
    assert "Check the relief valve daily." in [item["source_text"] for item in issue["context"]]
    assert [term["source"].casefold() for term in issue["terms"]] == ["relief valve"]
    assert issue["terms"][0]["target"] == "предохранительный клапан"
    assert issue["actions"][:4] == ["comment", "confirm", "reject", "request_clarification"]


@requires_database
async def test_repeated_source_text_raises_the_impact(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    repeated = next(row for row in rows if row["source_text"].startswith("Check"))

    issue = await registered(db_client, account, repeated)

    # Два раза в первой главе и один во второй.
    assert issue["impact_count"] == 3


# ── отбор, статистика, выгрузка, поиск ──


@requires_database
async def test_filters_sort_and_stats(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    book_id, chapter_id, rows = await translated(db_client, session, account)
    block = paragraph(rows)

    critical = await registered(db_client, account, block, severity="critical")
    major = await registered(db_client, account, block, severity="major", category="semantic")
    minor = await registered(db_client, account, block, severity="minor", category="style")
    await act(db_client, account, minor["id"], "reject", note="Вкусовщина")

    ordered = await db_client.get("/issues?sort=priority&order=desc", headers=account.headers)
    assert [item["id"] for item in ordered.json()["items"]] == [
        critical["id"],
        major["id"],
        minor["id"],
    ]

    for query, expected in (
        ("severity=critical", [critical["id"]]),
        ("category=semantic", [major["id"]]),
        ("state=rejected", [minor["id"]]),
        (
            "state=new&state=rejected&sort=created&order=asc",
            [critical["id"], major["id"], minor["id"]],
        ),
        (f"query={major['code']}", [major["id"]]),
        ("query=%25", []),
    ):
        found = await db_client.get(f"/issues?{query}", headers=account.headers)
        assert found.status_code == 200, found.text
        assert [item["id"] for item in found.json()["items"]] == expected, query

    stats = await db_client.get(f"/issues/stats?book_id={book_id}", headers=account.headers)
    assert stats.json() == {
        "total": 3,
        "by_status": {"new": 2, "rejected": 1},
        "by_severity": {"critical": 1, "major": 1, "minor": 1},
        "by_category": {"number": 1, "semantic": 1, "style": 1},
        "open_critical": 1,
        "open_major": 1,
    }

    chapter = await db_client.get(f"/issues/stats?chapter_id={chapter_id}", headers=account.headers)
    assert chapter.json()["total"] == 3


@requires_database
async def test_archive_hides_only_what_is_decided_and_keeps_the_record(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))

    await act(db_client, account, issue["id"], "archive", expect=409)

    await act(db_client, account, issue["id"], "reject", note="Не ошибка")
    archived = await act(db_client, account, issue["id"], "archive")
    assert archived["archived_at"] is not None

    assert (await db_client.get("/issues", headers=account.headers)).json()["total"] == 0
    assert (await db_client.get("/issues?archived=true", headers=account.headers)).json()[
        "total"
    ] == 1

    await act(db_client, account, issue["id"], "reopen", expect=409, note="Из архива")
    assert (await read(db_client, account, issue["id"]))["actions"] == ["restore"]

    await act(db_client, account, issue["id"], "restore")
    assert (await db_client.get("/issues", headers=account.headers)).json()["total"] == 1


@requires_database
async def test_search_finds_issue_by_its_code(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))

    found = await db_client.get(f"/search?query={issue['code'].lower()}", headers=account.headers)

    assert found.status_code == 200, found.text
    assert [item["id"] for item in found.json()["issues"]["items"]] == [issue["id"]]


@requires_database
async def test_export_files_keep_formula_like_text_harmless(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapter_id, rows = await translated(db_client, session, account)
    await registered(db_client, account, paragraph(rows), description="=HYPERLINK(1)")

    as_csv = await db_client.get(
        f"/issues/export?format=csv&chapter_id={chapter_id}", headers=account.headers
    )
    assert as_csv.status_code == 200, as_csv.text
    assert "attachment" in as_csv.headers["content-disposition"]
    assert as_csv.headers["x-content-type-options"] == "nosniff"

    lines = list(csv.reader(io.StringIO(as_csv.content.decode("utf-8-sig"))))
    assert lines[1][0] == "BK01-CH01-ERR-0001"
    assert lines[1][10] == "'=HYPERLINK(1)"

    as_xlsx = await db_client.get("/issues/export?format=xlsx", headers=account.headers)
    assert as_xlsx.status_code == 200, as_xlsx.text

    sheet = load_workbook(io.BytesIO(as_xlsx.content)).active
    cell = next(sheet.iter_rows(min_row=2))[10]
    assert cell.value == "=HYPERLINK(1)"
    assert cell.data_type == "s"

    refused = await db_client.get("/issues/export?format=exe", headers=account.headers)
    assert refused.status_code == 422


@requires_database
async def test_overview_counts_open_issues(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    block = paragraph(rows)

    await registered(db_client, account, block, severity="critical")
    rejected = await registered(db_client, account, block)
    await act(db_client, account, rejected["id"], "reject", note="Нет")

    overview = await db_client.get("/overview", headers=account.headers)

    assert overview.json()["open_issues"] == 1
    assert overview.json()["open_critical"] == 1


# ── вложения ──


@requires_database
async def test_attachment_is_judged_by_its_bytes(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))
    target = f"/issues/{issue['id']}/attachments"

    for name, body, media in (
        ("страница.png", b"<svg><script>alert(1)</script></svg>", "image/png"),
        ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        ("a.exe", b"MZ\x90\x00", "application/octet-stream"),
    ):
        refused = await db_client.post(
            target, headers=account.headers, files={"file": (name, body, media)}
        )
        assert refused.status_code == 415, name

    # Тип сказан неверно, но байты — настоящая картинка: верят байтам.
    accepted = await db_client.post(
        target,
        headers=account.headers,
        files={"file": ("../../стр 12.txt", PNG, "text/plain")},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["media_type"] == "image/png"
    assert accepted.json()["filename"] == "стр 12.txt"

    served = await db_client.get(f"{target}/{accepted.json()['id']}", headers=account.headers)
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]

    detail = await read(db_client, account, issue["id"])
    assert [item["id"] for item in detail["attachments"]] == [accepted.json()["id"]]
    assert detail["events"][-1]["kind"] == "attached"
    assert detail["events"][-1]["payload"]["filename"] == "стр 12.txt"


@requires_database
async def test_attachment_of_another_workspace_is_not_served(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, _, rows = await translated(db_client, session, account)
    issue = await registered(db_client, account, paragraph(rows))
    target = f"/issues/{issue['id']}/attachments"
    accepted = await db_client.post(
        target, headers=account.headers, files={"file": ("a.png", PNG, "image/png")}
    )

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    served = await db_client.get(f"{target}/{accepted.json()['id']}", headers=stranger.headers)
    assert served.status_code == 404

    planted = await db_client.post(
        target, headers=stranger.headers, files={"file": ("a.png", PNG, "image/png")}
    )
    assert planted.status_code == 404
