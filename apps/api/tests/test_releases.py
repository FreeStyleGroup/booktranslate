"""Финальные версии глав, сборка книги и читательская версия."""

import io
import zipfile

import docx
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.export.base import Rendered
from app.services.export.docx_writer import MEDIA_TYPE, without_comments
from app.services.export.scan import readable_text, scan
from app.worker import once
from tests.conftest import requires_database
from tests.factories import Account, register
from tests.test_chapter_translation import STOP, blocks, ready, translate
from tests.test_fixes import edit, regression, settle
from tests.test_issues import act, registered
from tests.test_reviews import PARAGRAPH, finish, row_of, start
from tests.test_team import accept_as_new, invite, token_of

# ── проверка готового файла: без базы ──


def test_scan_finds_service_codes() -> None:
    assert scan("Текст CH03-B0042 дальше.")
    assert scan("См. BK01-CH03-ERR-0001.")
    assert scan("Ошибка ERR-0001.")
    assert scan("BK01-CH03-FINAL-v1.0")
    assert scan("BK01-RELEASE-v1.2")
    assert scan("Рисунок CH03-FIG001.")
    assert scan("Текст ⟦1⟧ тут.")


def test_scan_passes_clean_text() -> None:
    assert scan("Насос защищён клапаном. Давление 12,5 бар, раздел 3.2, деталь B0042.") == []


def test_string_from_the_book_itself_is_not_a_service_code() -> None:
    assert scan("Деталь CH01-B0001 снята.", source_texts=["Part CH01-B0001 removed."]) == []


def test_scan_finds_long_note_but_not_a_short_one() -> None:
    long_note = "Здесь проверяющий написал длинную заметку о спорном месте."

    assert scan(f"Текст. {long_note}", notes=[long_note])
    assert scan("Текст про радиус.", notes=["радиус"]) == []


def word_file(*paragraphs: str, comment: str | None = None) -> bytes:
    document = docx.Document()
    for item in paragraphs:
        paragraph = document.add_paragraph(item)
    if comment is not None:
        document.add_comment(paragraph.runs, text=comment, author="QA")

    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()


def test_scan_reads_docx_split_into_runs() -> None:
    document = docx.Document()
    paragraph = document.add_paragraph("Текст CH03-")
    paragraph.add_run("B0042 дальше")
    buffer = io.BytesIO()
    document.save(buffer)

    rendered = Rendered(content=buffer.getvalue(), media_type=MEDIA_TYPE, suffix=".docx")
    assert scan(readable_text(rendered))


def test_comments_are_removed_from_the_reader_file() -> None:
    content = word_file("Абзац книги.", comment="Замечание CH03-B0042")
    rendered = Rendered(content=content, media_type=MEDIA_TYPE, suffix=".docx")
    assert scan(readable_text(rendered))

    cleaned = without_comments(content)
    names = zipfile.ZipFile(io.BytesIO(cleaned)).namelist()
    assert not [name for name in names if "comments" in name]
    assert scan(readable_text(Rendered(cleaned, MEDIA_TYPE, ".docx"))) == []
    # Файл после чистки открывается, и текст на месте.
    assert docx.Document(io.BytesIO(cleaned)).paragraphs[0].text == "Абзац книги."


def test_file_without_comments_is_left_as_is() -> None:
    content = word_file("Абзац книги.")

    assert without_comments(content) == content


# ── финальная версия главы ──


async def reviewed(
    client: AsyncClient, session: AsyncSession, account: Account, chapter_id: str
) -> None:
    """Пройти три работы: техническую, литературную с проверкой и сверку."""
    technical = await start(client, account, chapter_id, "technical")
    await finish(client, account, technical["id"])
    literary = await start(client, account, chapter_id, "literary")
    await finish(client, account, literary["id"])
    assert await once(session, "test", STOP) is True
    final = await start(client, account, chapter_id, "final_compare")
    await finish(client, account, final["id"])


async def prepared(
    client: AsyncClient, session: AsyncSession, account: Account
) -> tuple[str, list[dict]]:
    """Книга: все главы переведены и прошли редактуру."""
    book_id, chapters = await ready(client, account)

    for chapter in chapters:
        await translate(client, session, account, chapter["id"])
        await reviewed(client, session, account, chapter["id"])

    return book_id, chapters


async def create(client: AsyncClient, account: Account, chapter_id: str, **body: object) -> dict:
    response = await client.post(
        f"/chapters/{chapter_id}/releases", headers=account.headers, json=body
    )
    assert response.status_code == 201, response.text

    result: dict = response.json()
    return result


async def approve_release(client: AsyncClient, account: Account, release_id: str) -> dict:
    response = await client.post(f"/chapter-releases/{release_id}/approve", headers=account.headers)
    assert response.status_code == 200, response.text

    result: dict = response.json()
    return result


async def approved(client: AsyncClient, account: Account, chapter_id: str) -> dict:
    return await approve_release(client, account, (await create(client, account, chapter_id))["id"])


async def gate_codes(client: AsyncClient, account: Account, chapter_id: str) -> set[str]:
    response = await client.get(f"/chapters/{chapter_id}/release-gate", headers=account.headers)
    assert response.status_code == 200, response.text

    return {item["code"] for item in response.json()["blockers"]}


@requires_database
async def test_gate_names_every_reason(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]

    before = await gate_codes(db_client, account, chapter_id)
    assert {"untranslated", "technical_missing", "literary_missing", "final_missing"} <= before

    await translate(db_client, session, account, chapter_id)
    after = await gate_codes(db_client, account, chapter_id)
    assert "untranslated" not in after
    assert "technical_missing" in after

    refused = await db_client.post(
        f"/chapters/{chapter_id}/releases", headers=account.headers, json={}
    )
    assert refused.status_code == 409
    assert "Техническая редактура" in refused.json()["detail"]


@requires_database
async def test_gate_is_held_by_open_issue_and_stale_compare(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    assert await gate_codes(db_client, account, chapter_id) == set()

    rows = await blocks(db_client, account, chapter_id)
    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block, severity="critical")
    assert "open_critical" in await gate_codes(db_client, account, chapter_id)

    await act(db_client, account, issue["id"], "confirm")
    await edit(db_client, account, issue["id"], block, "Клапан защищает насос.")

    # Текст изменился: сверка была про другой текст, хотя всё остальное на месте.
    codes = await gate_codes(db_client, account, chapter_id)
    assert "final_stale" in codes
    assert "formal_incomplete" in codes


@requires_database
async def test_release_freezes_exact_revisions(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)

    release = await create(db_client, account, chapter_id)
    assert release["code"] == "BK01-CH01-FINAL-v1.0"
    assert release["status"] == "draft"
    assert release["objects"] > 0

    found = await db_client.get(
        f"/chapter-releases/{release['id']}/manifest", headers=account.headers
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["intact"] is True

    rows = await blocks(db_client, account, chapter_id)
    assert {row["revision_id"] for row in body["manifest"]["blocks"]} == {
        row["current"]["id"] for row in rows
    }


@requires_database
async def test_working_text_does_not_touch_the_final_version(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    release = await approved(db_client, account, chapter_id)
    assert release["working_differs"] is False

    rows = await blocks(db_client, account, chapter_id)
    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block)
    await act(db_client, account, issue["id"], "confirm")
    await edit(db_client, account, issue["id"], block, "Рабочий текст ушёл вперёд.")

    state = await db_client.get(f"/chapter-releases/{release['id']}", headers=account.headers)
    assert state.json()["working_differs"] is True
    assert state.json()["manifest_hash"] == release["manifest_hash"]

    changes = await db_client.get(
        f"/chapter-releases/{release['id']}/changes", headers=account.headers
    )
    assert changes.status_code == 200, changes.text
    assert [row["block_id"] for row in changes.json()] == [block["id"]]
    assert changes.json()[0]["working_text"] == "Рабочий текст ушёл вперёд."
    assert changes.json()[0]["final_text"] == block["current"]["text"]

    exported = await db_client.get(
        f"/chapter-releases/{release['id']}/export?format=text", headers=account.headers
    )
    assert exported.status_code == 200, exported.text
    assert block["current"]["text"] in exported.text
    assert "Рабочий текст ушёл вперёд." not in exported.text


@requires_database
async def test_versions_grow_and_same_text_is_refused(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    first = await approved(db_client, account, chapter_id)

    same = await db_client.post(
        f"/chapters/{chapter_id}/releases", headers=account.headers, json={}
    )
    assert same.status_code == 409
    assert first["code"] in same.json()["detail"]

    rows = await blocks(db_client, account, chapter_id)
    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block, severity="minor")
    await act(db_client, account, issue["id"], "confirm")
    await edit(
        db_client, account, issue["id"], block, "Предохранительный клапан надёжно защищает насос."
    )

    # Текст изменился: регрессия, формальная проверка и сверка нужны заново.
    run = await regression(db_client, account, issue["id"])
    await settle(db_client, account, run)

    checked = await db_client.post(
        f"/chapters/{chapter_id}/qa", headers=account.headers, json={"kind": "deterministic"}
    )
    assert checked.status_code == 201, checked.text
    assert await once(session, "test", STOP) is True
    final = await start(db_client, account, chapter_id, "final_compare")
    await finish(db_client, account, final["id"])

    second = await create(db_client, account, chapter_id)
    assert second["version"] == "v1.1"
    assert second["code"].endswith("-FINAL-v1.1")

    await approve_release(db_client, account, second["id"])
    assert await gate_codes(db_client, account, chapter_id) == set()


@requires_database
async def test_draft_is_one_and_can_be_discarded(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    draft = await create(db_client, account, chapter_id)

    second = await db_client.post(
        f"/chapters/{chapter_id}/releases", headers=account.headers, json={"major": True}
    )
    assert second.status_code == 409

    no_reader = await db_client.get(
        f"/chapter-releases/{draft['id']}/export?format=text", headers=account.headers
    )
    assert no_reader.status_code == 409

    gone = await db_client.delete(f"/chapter-releases/{draft['id']}", headers=account.headers)
    assert gone.status_code == 204

    again = await create(db_client, account, chapter_id, major=True)
    assert again["version"] == "v1.0"


@requires_database
async def test_approved_release_is_immutable_in_the_database(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    release = await approved(db_client, account, chapter_id)

    refused = await db_client.delete(f"/chapter-releases/{release['id']}", headers=account.headers)
    assert refused.status_code == 409

    for statement in (
        "UPDATE chapter_releases SET manifest_hash = 'x' WHERE id = :id",
        "UPDATE chapter_releases SET status = 'DRAFT' WHERE id = :id",
        "DELETE FROM chapter_releases WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(text(statement), {"id": release["id"]})


@requires_database
async def test_draft_composition_cannot_be_changed_in_the_database(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    draft = await create(db_client, account, chapter_id)

    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE chapter_releases SET manifest = '{}'::jsonb WHERE id = :id"),
                {"id": draft["id"]},
            )


@requires_database
async def test_approval_notices_a_text_changed_after_creation(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    draft = await create(db_client, account, chapter_id)

    rows = await blocks(db_client, account, chapter_id)
    block = row_of(rows, PARAGRAPH)
    issue = await registered(db_client, account, block)
    await act(db_client, account, issue["id"], "confirm")
    await edit(db_client, account, issue["id"], block, "Текст успели изменить.")

    refused = await db_client.post(
        f"/chapter-releases/{draft['id']}/approve", headers=account.headers
    )
    assert refused.status_code == 409
    assert "изменился" in refused.json()["detail"]


# ── рабочая и читательская выгрузки ──


@requires_database
async def test_working_export_has_codes_and_reader_has_none(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await ready(db_client, account)
    chapter_id = chapters[0]["id"]
    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    release = await approved(db_client, account, chapter_id)

    working = await db_client.get(
        f"/chapters/{chapter_id}/export?format=text&codes=true", headers=account.headers
    )
    assert working.status_code == 200, working.text
    assert "[CH01-B0001]" in working.text
    assert "%D1%80%D0%B0%D0%B1%D0%BE%D1%87%D0%B0%D1%8F" in working.headers["content-disposition"]

    for export_format in ("text", "markdown", "docx"):
        reader = await db_client.get(
            f"/chapter-releases/{release['id']}/export?format={export_format}",
            headers=account.headers,
        )
        assert reader.status_code == 200, reader.text
        suffix = ".docx" if export_format == "docx" else ".txt"
        content = readable_text(Rendered(reader.content, "", suffix))
        assert scan(content) == [], export_format
        assert "CH01-B0001" not in content
        assert release["code"] in reader.headers["content-disposition"]


# ── сборка книги ──


@requires_database
async def test_assembly_blocks_missing_and_draft_chapters(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    first = await approved(db_client, account, chapters[0]["id"])
    draft = await create(db_client, account, chapters[1]["id"])

    plan = await db_client.get(f"/books/{book_id}/assembly", headers=account.headers)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["ready"] is False
    assert "missing_chapter" in {row["code"] for row in body["problems"]}
    # Подсказка берёт только утверждённое: черновик сам в выпуск не попадёт.
    assert body["items"][1]["chosen_id"] is None

    refused = await db_client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [first["id"], draft["id"]]},
    )
    assert refused.status_code == 409
    assert "не утверждена" in refused.json()["detail"]


@requires_database
async def test_assembly_is_deterministic_and_rebuild_returns_the_same(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    releases = [await approved(db_client, account, row["id"]) for row in chapters]
    ids = [row["id"] for row in releases]

    built = await db_client.post(
        f"/books/{book_id}/releases", headers=account.headers, json={"chapter_release_ids": ids}
    )
    assert built.status_code == 201, built.text
    release = built.json()
    assert release["code"] == "BK01-RELEASE-v1.0"
    assert [row["release_code"] for row in release["chapters"]] == [row["code"] for row in releases]
    assert release["toc"]

    rebuilt = await db_client.post(
        f"/books/{book_id}/releases", headers=account.headers, json={"chapter_release_ids": ids}
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["id"] == release["id"]
    assert rebuilt.json()["created"] is False

    listing = await db_client.get(f"/books/{book_id}/releases", headers=account.headers)
    assert len(listing.json()) == 1


@requires_database
async def test_assembly_refuses_wrong_order_and_duplicates(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    releases = [await approved(db_client, account, row["id"]) for row in chapters]

    wrong = await db_client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [releases[1]["id"], releases[0]["id"]]},
    )
    assert wrong.status_code == 409
    assert "не на своём месте" in wrong.json()["detail"]

    twice = await db_client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [releases[0]["id"], releases[0]["id"], releases[1]["id"]]},
    )
    assert twice.status_code == 409
    assert "дважды" in twice.json()["detail"]


@requires_database
async def test_book_reader_export_is_clean_and_composition_is_guarded(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    releases = [await approved(db_client, account, row["id"]) for row in chapters]
    built = await db_client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [row["id"] for row in releases]},
    )
    release = built.json()

    reader = await db_client.get(
        f"/book-releases/{release['id']}/export?format=text", headers=account.headers
    )
    assert reader.status_code == 200, reader.text
    assert scan(reader.text) == []
    assert release["code"] in reader.headers["content-disposition"]

    for statement in (
        "DELETE FROM book_releases WHERE id = :id",
        "UPDATE book_releases SET manifest_hash = 'x' WHERE id = :id",
        "DELETE FROM book_release_chapters WHERE release_id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(text(statement), {"id": release["id"]})

    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.execute(
                text("DELETE FROM chapter_releases WHERE id = :id"), {"id": releases[0]["id"]}
            )


# ── права и изоляция ──


@requires_database
async def test_roles_and_isolation(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    chapter_id = chapters[0]["id"]
    draft = await create(db_client, account, chapter_id)

    invited = await invite(db_client, account, role="translator")
    translator = await accept_as_new(db_client, token_of(invited))

    refused = await db_client.post(f"/chapter-releases/{draft['id']}/approve", headers=translator)
    assert refused.status_code == 403

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    for method, path in (
        ("GET", f"/chapters/{chapter_id}/release-gate"),
        ("GET", f"/chapter-releases/{draft['id']}"),
        ("GET", f"/chapter-releases/{draft['id']}/manifest"),
        ("GET", f"/chapter-releases/{draft['id']}/export?format=text"),
        ("POST", f"/chapter-releases/{draft['id']}/approve"),
        ("GET", f"/books/{book_id}/assembly"),
    ):
        response = await db_client.request(method, path, headers=stranger.headers)
        assert response.status_code == 404, path


@requires_database
async def test_project_with_releases_is_not_deleted(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    await create(db_client, account, chapters[0]["id"])

    book = await db_client.get(f"/books/{book_id}", headers=account.headers)
    refused = await db_client.delete(
        f"/projects/{book.json()['project_id']}", headers=account.headers
    )
    assert refused.status_code == 409
    assert "выпуски" in refused.json()["detail"]
