"""Файлы выпуска, постраничный аудит и контроль выпуска."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker
from app.models.block import BlockKind
from app.models.issue import IssueAttachment
from app.services.export.pdf import (
    FigureElement,
    PdfDocument,
    TableCell,
    TableElement,
    TextElement,
    build_html,
    page_count,
    page_png,
    render_stub,
)
from app.services.storage import LocalStorage
from app.worker import once
from tests.conftest import requires_database
from tests.factories import Account, register
from tests.test_chapter_translation import STOP
from tests.test_issues import act
from tests.test_releases import approved, prepared
from tests.test_team import accept_as_new, invite, token_of


@pytest.fixture(autouse=True)
def worker_storage(monkeypatch: pytest.MonkeyPatch, storage_root: Path) -> None:
    """Рабочий процесс кладёт файлы туда же, откуда их читает API в тесте."""
    monkeypatch.setattr(worker, "get_storage", lambda: LocalStorage(storage_root))


# ── разметка: без базы ──


def test_html_escapes_everything_from_the_book() -> None:
    document = PdfDocument(
        title="<script>alert(1)</script>",
        language="ru",
        elements=[
            TextElement(
                block_id="a", kind=BlockKind.PARAGRAPH, text='<img src="file:///etc/passwd">'
            ),
            TableElement(rows=[[TableCell(text="<b>жирный</b>")]]),
        ],
    )

    built = build_html(document)
    assert "<script>" not in built
    assert 'src="file:' not in built
    assert "<b>жирный</b>" not in built


def test_html_takes_only_known_language() -> None:
    bad = PdfDocument(title="T", language='ru"><script>', elements=[])
    assert 'lang="ru"' in build_html(bad)


def test_table_keeps_merged_cells() -> None:
    built = build_html(
        PdfDocument(
            title="T",
            language="ru",
            elements=[
                TableElement(rows=[[TableCell(text="A", rowspan=2, colspan=3, header=True)]])
            ],
        )
    )
    assert 'rowspan="2"' in built
    assert 'colspan="3"' in built
    assert "<th" in built


def test_figure_uses_only_given_address() -> None:
    built = build_html(
        PdfDocument(
            title="T",
            language="ru",
            elements=[FigureElement(urls=["asset:0"], alts=['"><script>'])],
        )
    )
    assert 'src="asset:0"' in built
    assert "<script>" not in built.split("</style>", 1)[1]


def test_stub_is_a_real_pdf_with_pages_and_anchors() -> None:
    document = PdfDocument(
        title="T",
        language="ru",
        elements=[
            TextElement(block_id=f"b{i}", kind=BlockKind.PARAGRAPH, text="x") for i in range(7)
        ],
    )
    rendered = render_stub(document)

    assert page_count(rendered.content) == len(rendered.page_map) == 3
    assert rendered.page_map[0] == ["b0", "b1", "b2"]
    assert page_png(rendered.content, 1).startswith(b"\x89PNG")


# ── выпуск до файлов ──


async def built_release(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, dict]:
    book_id, chapters = await prepared(client, session, account)
    releases = [await approved(client, account, row["id"]) for row in chapters]
    response = await client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [row["id"] for row in releases]},
    )
    assert response.status_code == 201, response.text

    return book_id, response.json()


async def gate(client: AsyncClient, account: Account, release_id: str) -> dict:
    response = await client.get(f"/releases/{release_id}/gate", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


def codes(body: dict) -> set[str]:
    return {row["code"] for row in body["blockers"]}


async def rendered(
    client: AsyncClient, session: AsyncSession, account: Account, release_id: str
) -> dict:
    """Собрать файлы и вернуть текущий PDF."""
    response = await client.post(f"/book-releases/{release_id}/artifacts", headers=account.headers)
    assert response.status_code == 202, response.text
    assert await once(session, "test", STOP) is True

    files = await client.get(f"/book-releases/{release_id}/artifacts", headers=account.headers)
    assert files.status_code == 200, files.text
    body = files.json()
    assert body["job_state"] == "done", body

    return next(row for row in body["artifacts"] if row["format"] == "pdf")


async def audit_all(client: AsyncClient, account: Account, pdf: dict) -> None:
    for number in range(1, pdf["page_count"] + 1):
        marked = await client.post(
            f"/artifacts/{pdf['id']}/pages/{number}", headers=account.headers
        )
        assert marked.status_code == 200, marked.text


@requires_database
async def test_gate_lists_missing_files_and_pass_is_refused(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)

    body = await gate(db_client, account, release["id"])
    assert body["ready"] is False
    assert "artifact_missing" in codes(body)
    assert "pages_unreviewed" in codes(body)
    assert {row["code"] for row in body["checks"]} >= {"artifacts_current", "pages_audited"}

    refused = await db_client.post(f"/releases/{release['id']}/pass", headers=account.headers)
    assert refused.status_code == 409
    assert "не пройден" in refused.json()["detail"]


# ── файлы и аудит ──


@requires_database
async def test_render_stores_both_files_from_one_manifest(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    pdf = await rendered(db_client, session, account, release["id"])

    files = (
        await db_client.get(f"/book-releases/{release['id']}/artifacts", headers=account.headers)
    ).json()
    assert {row["format"] for row in files["artifacts"]} == {"docx", "pdf"}
    assert {row["manifest_hash"] for row in files["artifacts"]} == {release["manifest_hash"]}
    assert all(len(row["checksum"]) == 64 for row in files["artifacts"])
    assert pdf["page_count"] > 0

    download = await db_client.get(f"/artifacts/{pdf['id']}/download", headers=account.headers)
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")
    assert download.headers["x-checksum-sha256"] == pdf["checksum"]
    assert release["code"] in download.headers["content-disposition"]

    image = await db_client.get(f"/artifacts/{pdf['id']}/pages/1/image", headers=account.headers)
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")

    missing = await db_client.get(
        f"/artifacts/{pdf['id']}/pages/{pdf['page_count'] + 1}/image", headers=account.headers
    )
    assert missing.status_code == 404


@requires_database
async def test_full_audit_opens_pass_and_everything_freezes(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    pdf = await rendered(db_client, session, account, release["id"])

    assert "pages_unreviewed" in codes(await gate(db_client, account, release["id"]))
    await audit_all(db_client, account, pdf)

    body = await gate(db_client, account, release["id"])
    assert body["ready"] is True, body["blockers"]
    assert all(row["passed"] for row in body["checks"])

    passed = await db_client.post(f"/releases/{release['id']}/pass", headers=account.headers)
    assert passed.status_code == 200, passed.text
    result = passed.json()
    assert result["status"] == "passed"
    assert result["passed_at"] is not None
    assert result["snapshot"]["ready"] is True

    twice = await db_client.post(f"/releases/{release['id']}/pass", headers=account.headers)
    assert twice.status_code == 409

    again = await db_client.post(
        f"/book-releases/{release['id']}/artifacts", headers=account.headers
    )
    assert again.status_code == 409

    for statement in (
        "UPDATE book_releases SET status = 'BUILT' WHERE id = :id",
        "UPDATE export_artifacts SET checksum = 'x' WHERE release_id = :id",
        "DELETE FROM export_artifacts WHERE release_id = :id",
        "UPDATE release_passes SET manifest_hash = 'x' WHERE release_id = :id",
        "DELETE FROM release_passes WHERE release_id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(text(statement), {"id": release["id"]})

    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE page_audits SET status = 'UNREVIEWED' WHERE artifact_id = :id"),
                {"id": pdf["id"]},
            )


@requires_database
async def test_pass_cannot_be_set_in_the_database_without_a_record(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)

    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE book_releases SET status = 'PASSED' WHERE id = :id"),
                {"id": release["id"]},
            )


@requires_database
async def test_page_issue_keeps_page_and_snapshot_and_holds_pass(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    pdf = await rendered(db_client, session, account, release["id"])
    await audit_all(db_client, account, pdf)

    registered = await db_client.post(
        f"/artifacts/{pdf['id']}/pages/1/issue",
        headers=account.headers,
        json={"severity": "major", "description": "Таблица вылезла за поле"},
    )
    assert registered.status_code == 200, registered.text
    found = registered.json()
    assert found["page"]["status"] == "issue"

    issue = (await db_client.get(f"/issues/{found['issue_id']}", headers=account.headers)).json()
    assert issue["category"] == "layout"
    assert "Страница 1" in issue["description"]

    attachment = await session.scalar(
        select(IssueAttachment).where(IssueAttachment.issue_id == found["issue_id"])
    )
    assert attachment is not None

    body = await gate(db_client, account, release["id"])
    assert {"page_issue", "open_major"} <= codes(body)
    blocker = next(row for row in body["blockers"] if row["code"] == "open_major")
    assert blocker["issue_id"] == found["issue_id"]

    # Пока замечание открыто, страницу верной не отметить.
    refused = await db_client.post(f"/artifacts/{pdf['id']}/pages/1", headers=account.headers)
    assert refused.status_code == 409
    assert found["issue_code"] in refused.json()["detail"]

    await act(db_client, account, found["issue_id"], "reject", note="Так и задумано")
    allowed = await db_client.post(f"/artifacts/{pdf['id']}/pages/1", headers=account.headers)
    assert allowed.status_code == 200, allowed.text
    assert (await gate(db_client, account, release["id"]))["ready"] is True


@requires_database
async def test_rerender_makes_old_audit_stale(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    first = await rendered(db_client, session, account, release["id"])
    await audit_all(db_client, account, first)

    second = await rendered(db_client, session, account, release["id"])
    assert second["id"] != first["id"]

    old = (await db_client.get(f"/artifacts/{first['id']}/pages", headers=account.headers)).json()
    assert {row["status"] for row in old} == {"stale"}

    new = (await db_client.get(f"/artifacts/{second['id']}/pages", headers=account.headers)).json()
    assert {row["status"] for row in new} == {"unreviewed"}

    refused = await db_client.post(f"/artifacts/{first['id']}/pages/1", headers=account.headers)
    assert refused.status_code == 409

    assert "pages_unreviewed" in codes(await gate(db_client, account, release["id"]))

    files = (
        await db_client.get(f"/book-releases/{release['id']}/artifacts", headers=account.headers)
    ).json()
    assert first["id"] in {row["id"] for row in files["previous"]}


@requires_database
async def test_second_render_while_one_is_queued_is_refused(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)

    first = await db_client.post(
        f"/book-releases/{release['id']}/artifacts", headers=account.headers
    )
    assert first.status_code == 202, first.text

    second = await db_client.post(
        f"/book-releases/{release['id']}/artifacts", headers=account.headers
    )
    assert second.status_code == 409
    assert "render_running" in codes(await gate(db_client, account, release["id"]))


@requires_database
async def test_replaced_file_in_storage_stops_pass(
    db_client: AsyncClient, session: AsyncSession, storage_root: Path
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    pdf = await rendered(db_client, session, account, release["id"])
    await audit_all(db_client, account, pdf)

    key = await session.scalar(
        text("SELECT storage_key FROM export_artifacts WHERE id = :id"), {"id": pdf["id"]}
    )
    path = LocalStorage(storage_root)._path(key)
    path.write_bytes(path.read_bytes() + b"\n% changed")

    refused = await db_client.post(f"/releases/{release['id']}/pass", headers=account.headers)
    assert refused.status_code == 409
    assert "не совпадает" in refused.json()["detail"]


@requires_database
async def test_minor_issue_holds_release_only_by_policy(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    pdf = await rendered(db_client, session, account, release["id"])
    await audit_all(db_client, account, pdf)

    registered = await db_client.post(
        f"/artifacts/{pdf['id']}/pages/1/issue",
        headers=account.headers,
        json={"severity": "minor", "description": "Висячая строка"},
    )
    assert registered.status_code == 200, registered.text
    assert "open_minor" not in codes(await gate(db_client, account, release["id"]))

    changed = await db_client.put(
        "/settings/workspace", headers=account.headers, json={"minor_blocks_release": True}
    )
    assert changed.status_code == 200, changed.text
    assert "open_minor" in codes(await gate(db_client, account, release["id"]))


# ── права и изоляция ──


@requires_database
async def test_roles_and_isolation(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, release = await built_release(db_client, session, account)
    pdf = await rendered(db_client, session, account, release["id"])

    invited = await invite(db_client, account, role="translator")
    translator = await accept_as_new(db_client, token_of(invited))

    for path in (
        f"/releases/{release['id']}/pass",
        f"/book-releases/{release['id']}/artifacts",
        f"/artifacts/{pdf['id']}/pages/1",
    ):
        response = await db_client.post(path, headers=translator)
        assert response.status_code == 403, path

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    for method, path in (
        ("GET", f"/releases/{release['id']}/gate"),
        ("POST", f"/releases/{release['id']}/pass"),
        ("GET", f"/artifacts/{pdf['id']}/download"),
        ("GET", f"/artifacts/{pdf['id']}/pages/1/image"),
        ("GET", f"/book-releases/{release['id']}/artifacts"),
    ):
        response = await db_client.request(method, path, headers=stranger.headers)
        assert response.status_code == 404, path
