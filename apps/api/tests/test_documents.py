"""Приём документов.

Проверяется то, за что придётся отвечать: формат определяется по
содержимому, повтор не плодит копии, чужой документ невидим, а лишний
байт сверх лимита не принимается.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.organization import Membership, Role
from tests.conftest import requires_database
from tests.factories import create_project, docx_bytes, register

MANUAL = b"Chapter 1. Safety instructions.\nDo not open the housing.\n"


@requires_database
async def test_upload_accepts_plain_text(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_format"] == "txt"
    assert body["status"] == "uploaded"
    assert body["size_bytes"] == len(MANUAL)
    assert body["original_filename"] == "manual.txt"
    # Название по умолчанию — имя файла без расширения: так документ можно
    # узнать в списке, не переименовывая его вручную.
    assert body["title"] == "manual"


@requires_database
async def test_same_file_returns_existing_document(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    first = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )
    second = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        # Имя другое, содержимое то же: считается тем же документом.
        files={"file": ("manual-copy.txt", MANUAL, "text/plain")},
    )

    assert first.status_code == 201
    # 200 вместо 201 — признак повтора: клиент отличает его по коду, а
    # платить за второй разбор одинакового содержимого незачем.
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]


@requires_database
async def test_format_is_detected_by_content_not_extension(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        # Расширение и заявленный тип врут — оба ставит человек.
        files={"file": ("manual.txt", docx_bytes(), "text/plain")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["source_format"] == "docx"


@requires_database
async def test_unknown_binary_is_rejected(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("firmware.bin", bytes(range(256)), "application/octet-stream")},
    )

    assert response.status_code == 415


@requires_database
async def test_empty_file_is_rejected(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400


@requires_database
async def test_oversized_file_is_rejected(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    # Лимит понижается на время теста, чтобы не гонять через сервер
    # пятьдесят мегабайт ради проверки одного условия.
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("huge.txt", b"a" * (1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413


@requires_database
async def test_content_is_returned_unchanged(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )
    document_id = uploaded.json()["id"]

    response = await db_client.get(f"/documents/{document_id}/content", headers=account.headers)

    assert response.status_code == 200, response.text
    assert response.content == MANUAL


@requires_database
async def test_foreign_document_is_invisible(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=owner.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )

    stranger = await register(
        db_client, email="stranger@example.com", organization_name="Другая контора"
    )

    response = await db_client.get(f"/documents/{uploaded.json()['id']}", headers=stranger.headers)

    assert response.status_code == 404


@requires_database
async def test_viewer_cannot_upload(db_client: AsyncClient, session: AsyncSession) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя контора")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    headers = guest.headers_for(owner.organization_id)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )

    assert response.status_code == 403
    # Смотреть при этом можно: запрет касается только изменения данных.
    assert (await db_client.get(f"/projects/{project_id}", headers=headers)).status_code == 200


@requires_database
async def test_delete_removes_record_and_file(db_client: AsyncClient, storage_root: Path) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )
    document_id = uploaded.json()["id"]

    assert [path for path in storage_root.rglob("*") if path.is_file()]

    deleted = await db_client.delete(f"/documents/{document_id}", headers=account.headers)

    assert deleted.status_code == 204

    gone = await db_client.get(f"/documents/{document_id}", headers=account.headers)
    assert gone.status_code == 404
    # Файл уходит вместе с записью: иначе хранилище растёт содержимым,
    # которое никому уже не принадлежит, а это ещё и данные клиента.
    assert not [path for path in storage_root.rglob("*") if path.is_file()]
