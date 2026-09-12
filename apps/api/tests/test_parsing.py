"""Разбор документа через API.

Проверяется то, за что придётся отвечать: сегменты появляются в порядке
исходника, повторный разбор не стирает работу человека молча, чужой документ
невидим, а сломанный файл оставляет причину, а не молчание.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.organization import Membership, Role
from tests.conftest import requires_database
from tests.factories import (
    Account,
    create_project,
    docx_bytes,
    epub_bytes,
    real_docx_bytes,
    register,
)

BOOK = (
    "Глава первая. Общие сведения.\n"
    "\n"
    "Устройство предназначено для непрерывной работы.\n"
    "\n"
    "Перед включением проверьте заземление.\n"
).encode()


async def upload(
    client: AsyncClient,
    account: Account,
    project_id: str,
    *,
    name: str = "book.txt",
    data: bytes = BOOK,
    content_type: str = "text/plain",
) -> str:
    response = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": (name, data, content_type)},
    )
    assert response.status_code == 201, response.text

    document_id: str = response.json()["id"]
    return document_id


@requires_database
async def test_parse_splits_text_into_segments(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)

    parsed = await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    assert parsed.status_code == 200, parsed.text
    assert parsed.json()["status"] == "parsed"
    assert parsed.json()["error"] is None

    listing = await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)

    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 3
    assert [item["position"] for item in body["items"]] == [0, 1, 2]
    assert body["items"][0]["source_text"] == "Глава первая. Общие сведения."
    assert body["items"][0]["status"] == "new"
    assert body["items"][0]["target_text"] is None


@requires_database
async def test_segments_are_paginated(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)
    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    page = await db_client.get(
        f"/documents/{document_id}/segments?limit=2&offset=1", headers=account.headers
    )

    body = page.json()
    # Общее число не зависит от страницы: по нему витрина рисует прокрутку.
    assert body["total"] == 3
    assert [item["position"] for item in body["items"]] == [1, 2]


@requires_database
async def test_second_parse_is_refused_without_force(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)

    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)
    again = await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    # Сегменты могли быть переведены и отредактированы: молча заменить их
    # значит потерять работу человека.
    assert again.status_code == 409

    forced = await db_client.post(
        f"/documents/{document_id}/parse?force=true", headers=account.headers
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "parsed"

    listing = await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    # Повтор заменяет, а не добавляет: сегментов столько же, сколько было.
    assert listing.json()["total"] == 3


async def leave_parsing(session: AsyncSession, document_id: str, *, silent_for: timedelta) -> None:
    """Так выглядит документ после контейнера, убитого посреди разбора."""
    await session.execute(
        update(Document)
        .where(Document.id == uuid.UUID(document_id))
        .values(status=DocumentStatus.PARSING, updated_at=datetime.now(UTC) - silent_for)
    )
    await session.commit()


@requires_database
async def test_stale_parse_is_released_only_with_force(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)
    await leave_parsing(session, document_id, silent_for=timedelta(hours=2))

    plain = await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)
    # Без force — отказ с подсказкой: отметку оставил убитый процесс, и
    # человек должен понять, как её снять.
    assert plain.status_code == 409
    assert "force=true" in plain.json()["detail"]

    forced = await db_client.post(
        f"/documents/{document_id}/parse?force=true", headers=account.headers
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["status"] == "parsed"


@requires_database
async def test_live_parse_is_not_released(db_client: AsyncClient, session: AsyncSession) -> None:
    """Разбор, отмечавшийся минуту назад, идёт: второй сотрёт сегменты у первого."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)
    await leave_parsing(session, document_id, silent_for=timedelta(minutes=1))

    forced = await db_client.post(
        f"/documents/{document_id}/parse?force=true", headers=account.headers
    )

    assert forced.status_code == 409


@requires_database
async def test_docx_structure_becomes_segment_kinds(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(
        db_client,
        account,
        project_id,
        name="manual.docx",
        data=real_docx_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)
    body = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()

    assert [item["kind"] for item in body["items"]] == [
        "heading",
        "paragraph",
        "list_item",
        "table_cell",
        "table_cell",
    ]


@requires_database
async def test_epub_chapters_keep_reading_order(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(
        db_client,
        account,
        project_id,
        name="book.epub",
        data=epub_bytes(),
        content_type="application/epub+zip",
    )

    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)
    body = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()

    assert [item["source_text"] for item in body["items"]] == [
        "Вторая глава",
        "Текст второй главы.",
        "Первая глава",
        "Текст первой главы.",
    ]
    assert body["items"][0]["source_location"]["chapter"] == 0


@requires_database
async def test_broken_file_leaves_reason(db_client: AsyncClient) -> None:
    """Заглушка DOCX проходит определение формата, но не открывается."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(
        db_client,
        account,
        project_id,
        name="broken.docx",
        data=docx_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    parsed = await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    assert parsed.status_code == 200
    body = parsed.json()
    assert body["status"] == "failed"
    # Причина видна пользователю: иначе он не знает, чинить файл или писать
    # в поддержку.
    assert body["error"]


@requires_database
async def test_broken_pdf_leaves_a_reason(db_client: AsyncClient) -> None:
    """Файл с сигнатурой PDF и мусором внутри — отказ с причиной, а не 500."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(
        db_client,
        account,
        project_id,
        name="manual.pdf",
        data=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n",
        content_type="application/pdf",
    )

    response = await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert "PDF" in response.json()["error"]


@requires_database
async def test_viewer_cannot_parse(db_client: AsyncClient, session: AsyncSession) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    document_id = await upload(db_client, owner, project_id)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя контора")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    headers = guest.headers_for(owner.organization_id)

    assert (
        await db_client.post(f"/documents/{document_id}/parse", headers=headers)
    ).status_code == 403
    # Читать сегменты наблюдателю можно: запрет касается только обработки.
    assert (
        await db_client.get(f"/documents/{document_id}/segments", headers=headers)
    ).status_code == 200


@requires_database
async def test_foreign_document_is_invisible(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    document_id = await upload(db_client, owner, project_id)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    assert (
        await db_client.post(f"/documents/{document_id}/parse", headers=stranger.headers)
    ).status_code == 404
    assert (
        await db_client.get(f"/documents/{document_id}/segments", headers=stranger.headers)
    ).status_code == 404
