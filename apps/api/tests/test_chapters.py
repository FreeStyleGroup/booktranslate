"""Главы книги: предложение, утверждение по порядку, разделение и слияние."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.organization import Membership, Role
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

BOOK = (
    b"<h1>Machine Learning for Asset Managers</h1>"
    b"<p>Preface.</p>"
    b"<h2>1. Introduction</h2><p>Why.</p>"
    b"<h3>1.1 Motivation</h3><p>Because.</p>"
    b"<h2>2. Denoising</h2><p>Noise.</p>"
    b"<h2>3. Distance Metrics</h2><p>Metrics.</p>"
)


async def book_with_source(client: AsyncClient, account: Account) -> tuple[str, str, str]:
    """Проект, книга и её основной источник — HTML с четырьмя главами."""
    project_id = await create_project(client, account)

    created = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "ML"}
    )
    assert created.status_code == 201, created.text
    book_id: str = created.json()["id"]

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("book.html", BOOK, "text/html")},
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    return project_id, book_id, uploaded.json()["id"]


async def proposed(client: AsyncClient, account: Account, book_id: str) -> list[dict]:
    response = await client.post(f"/books/{book_id}/chapters/proposal", headers=account.headers)
    assert response.status_code == 200, response.text

    chapters: list[dict] = response.json()["chapters"]
    return chapters


@requires_database
async def test_proposal_gives_drafts_without_codes(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, book_id, document_id = await book_with_source(db_client, account)

    chapters = await proposed(db_client, account, book_id)

    assert [chapter["title"] for chapter in chapters] == [
        "Machine Learning for Asset Managers",
        "1. Introduction",
        "2. Denoising",
        "3. Distance Metrics",
    ]
    assert [chapter["ordinal"] for chapter in chapters] == [1, 2, 3, 4]
    # Код выдаётся при утверждении: предложение можно отбросить, а
    # выданный номер второй главе не достаётся.
    assert all(chapter["code"] is None for chapter in chapters)
    assert all(chapter["boundary_status"] == "draft" for chapter in chapters)
    assert chapters[1]["inventory"] == {"heading": 2, "paragraph": 2}

    structure = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)
    assert structure.json()["source"]["id"] == document_id
    assert structure.json()["source_is_primary"] is True
    assert structure.json()["can_propose"] is True


@requires_database
async def test_proposal_needs_a_primary_source(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    created = await db_client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "Пустая"}
    )

    response = await db_client.post(
        f"/books/{created.json()['id']}/chapters/proposal", headers=account.headers
    )

    assert response.status_code == 409
    assert "основной источник" in response.json()["detail"]


@requires_database
async def test_chapters_are_approved_in_book_order(db_client: AsyncClient) -> None:
    """Код совпадает с местом главы: утверждение вразнобой отклоняется."""
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    chapters = await proposed(db_client, account, book_id)

    out_of_order = await db_client.post(
        f"/chapters/{chapters[2]['id']}/approval", headers=account.headers
    )
    assert out_of_order.status_code == 409
    assert "по порядку" in out_of_order.json()["detail"]

    first = await db_client.post(f"/chapters/{chapters[0]['id']}/approval", headers=account.headers)
    assert first.status_code == 200, first.text
    assert first.json()["code"] == "CH01"
    assert first.json()["boundary_status"] == "approved"
    assert first.json()["approved_at"] is not None

    everything = await db_client.post(
        f"/books/{book_id}/chapters/approval", headers=account.headers
    )
    assert everything.status_code == 200, everything.text
    codes = [chapter["code"] for chapter in everything.json()["chapters"]]
    assert codes == ["CH01", "CH02", "CH03", "CH04"]


@requires_database
async def test_approved_structure_is_not_proposed_again(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    chapters = await proposed(db_client, account, book_id)
    await db_client.post(f"/chapters/{chapters[0]['id']}/approval", headers=account.headers)

    again = await db_client.post(f"/books/{book_id}/chapters/proposal", headers=account.headers)

    assert again.status_code == 409
    structure = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)
    assert structure.json()["can_propose"] is False


@requires_database
async def test_split_keeps_code_and_reopens_boundaries(db_client: AsyncClient) -> None:
    """Разделённая глава сохраняет код, но возвращается в черновик с новой версией."""
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    await proposed(db_client, account, book_id)
    approved = await db_client.post(f"/books/{book_id}/chapters/approval", headers=account.headers)
    introduction = approved.json()["chapters"][1]
    subsection = introduction["sections"][1]["start"]

    response = await db_client.post(
        f"/chapters/{introduction['id']}/split",
        headers=account.headers,
        json={"at": subsection},
    )

    assert response.status_code == 200, response.text
    chapters = response.json()["chapters"]

    assert [chapter["ordinal"] for chapter in chapters] == [1, 2, 3, 4, 5]
    assert [chapter["code"] for chapter in chapters] == ["CH01", "CH02", None, "CH03", "CH04"]
    head, tail = chapters[1], chapters[2]
    assert head["boundary_status"] == "draft"
    assert head["boundary_version"] == 2
    assert head["source_end"] == tail["source_start"] == subsection
    assert tail["title"] == "1.1 Motivation"
    # Остальные главы не тронуты: утверждение относится к их границам,
    # а они не менялись.
    assert chapters[3]["boundary_status"] == "approved"


@requires_database
async def test_split_only_at_a_section_start(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    chapters = await proposed(db_client, account, book_id)
    introduction = chapters[1]

    response = await db_client.post(
        f"/chapters/{introduction['id']}/split",
        headers=account.headers,
        # Внутри раздела, но не его начало.
        json={"at": introduction["sections"][0]["start"] + 1},
    )

    assert response.status_code == 400


@requires_database
async def test_merged_code_is_never_issued_again(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Код поглощённой главы списан: новая глава получает следующий номер."""
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    await proposed(db_client, account, book_id)
    approved = await db_client.post(f"/books/{book_id}/chapters/approval", headers=account.headers)
    chapters = approved.json()["chapters"]

    merged = await db_client.post(f"/chapters/{chapters[1]['id']}/merge", headers=account.headers)

    assert merged.status_code == 200, merged.text
    after = merged.json()["chapters"]
    assert [chapter["code"] for chapter in after] == ["CH01", "CH02", "CH04"]
    assert [chapter["ordinal"] for chapter in after] == [1, 2, 3]
    assert after[1]["source_end"] == chapters[2]["source_end"]

    # Делим обратно — новая часть получит CH05, а не освободившийся CH03.
    split = await db_client.post(
        f"/chapters/{after[1]['id']}/split",
        headers=account.headers,
        json={"at": chapters[2]["source_start"]},
    )
    assert split.status_code == 200, split.text
    reapproved = await db_client.post(
        f"/books/{book_id}/chapters/approval", headers=account.headers
    )
    assert [chapter["code"] for chapter in reapproved.json()["chapters"]] == [
        "CH01",
        "CH02",
        "CH05",
        "CH04",
    ]

    event = await session.scalar(select(AuditEvent).where(AuditEvent.kind == "chapter.merged"))
    assert event is not None
    assert event.payload["retired_code"] == "CH03"


@requires_database
async def test_rename_keeps_approval(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    chapters = await proposed(db_client, account, book_id)
    await db_client.post(f"/chapters/{chapters[0]['id']}/approval", headers=account.headers)

    renamed = await db_client.patch(
        f"/chapters/{chapters[0]['id']}",
        headers=account.headers,
        json={"title": "  Вступление  "},
    )

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Вступление"
    assert renamed.json()["boundary_status"] == "approved"


@requires_database
async def test_decisions_are_recorded(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, account)
    chapters = await proposed(db_client, account, book_id)
    await db_client.post(f"/chapters/{chapters[0]['id']}/approval", headers=account.headers)

    events = {
        event.kind: event
        for event in await session.scalars(
            select(AuditEvent).where(AuditEvent.organization_id == account.organization_id)
        )
    }

    assert "chapters.proposed" in events
    approval = events["chapter.approved"]
    assert approval.actor_id == account.user_id
    assert approval.payload["code"] == "CH01"
    assert approval.payload["decided_by"] == "user"


@requires_database
async def test_viewer_cannot_change_structure(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    owner = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, owner)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя контора")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()
    headers = guest.headers_for(owner.organization_id)

    response = await db_client.post(f"/books/{book_id}/chapters/proposal", headers=headers)
    assert response.status_code == 403

    # Смотреть наблюдателю можно.
    looked = await db_client.get(f"/books/{book_id}/chapters", headers=headers)
    assert looked.status_code == 200


@requires_database
async def test_structure_is_invisible_to_another_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    _, book_id, _ = await book_with_source(db_client, owner)
    chapters = await proposed(db_client, owner, book_id)

    stranger = await register(
        db_client, email="stranger@example.com", organization_name="Чужая контора"
    )

    assert (
        await db_client.get(f"/books/{book_id}/chapters", headers=stranger.headers)
    ).status_code == 404
    assert (
        await db_client.post(f"/chapters/{chapters[0]['id']}/approval", headers=stranger.headers)
    ).status_code == 404


@requires_database
async def test_marked_source_cannot_be_deleted(db_client: AsyncClient) -> None:
    """Файл, по которому размечены главы, удаляется только вместе с книгой."""
    account = await register(db_client)
    project_id, book_id, document_id = await book_with_source(db_client, account)
    await proposed(db_client, account, book_id)

    refused = await db_client.delete(f"/documents/{document_id}", headers=account.headers)
    assert refused.status_code == 409
    assert "главы" in refused.json()["detail"]

    # Проект — вместе с книгой и её главами — удаляется: каскад не
    # спотыкается о собственные главы.
    removed = await db_client.delete(f"/projects/{project_id}", headers=account.headers)
    assert removed.status_code == 204, removed.text


@requires_database
async def test_structure_warns_when_primary_source_changed(db_client: AsyncClient) -> None:
    """Сменили основной источник — главы размечены по прежнему файлу, и это видно."""
    account = await register(db_client)
    _, book_id, document_id = await book_with_source(db_client, account)
    await proposed(db_client, account, book_id)

    demoted = await db_client.patch(
        f"/books/{book_id}/sources/{document_id}",
        headers=account.headers,
        json={"role": "visual_reference"},
    )
    assert demoted.status_code == 200, demoted.text

    structure = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)

    assert structure.json()["source_is_primary"] is False


@requires_database
async def test_untitled_chapter_takes_the_merged_title(db_client: AsyncClient) -> None:
    """Обложка без заголовка, слитая с титулом, получает название, а не «без названия»."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    created = await db_client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "ML"}
    )
    book_id = created.json()["id"]
    await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={
            "file": (
                "book.html",
                b"<p>Cover.</p><h2>One</h2><p>A.</p><h2>Two</h2><p>B.</p>",
                "text/html",
            )
        },
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    chapters = await proposed(db_client, account, book_id)
    assert chapters[0]["title"] is None

    merged = await db_client.post(f"/chapters/{chapters[0]['id']}/merge", headers=account.headers)

    assert merged.json()["chapters"][0]["title"] == "One"
