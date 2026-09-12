"""Проекты: создание, короткие имена и изоляция организаций."""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import create_project, register


@requires_database
async def test_project_gets_transliterated_slug(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.post(
        "/projects",
        headers=account.headers,
        json={
            "name": "Руководство по эксплуатации",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["slug"] == "rukovodstvo-po-ekspluatacii"


@requires_database
async def test_same_name_gets_distinct_slug(db_client: AsyncClient) -> None:
    account = await register(db_client)

    await create_project(db_client, account, name="Каталог")
    second = await db_client.post(
        "/projects",
        headers=account.headers,
        json={"name": "Каталог", "source_language": "en", "target_language": "ru"},
    )

    assert second.status_code == 201, second.text
    # Название повторять можно, адрес — нет: короткое имя получает суффикс.
    assert second.json()["slug"] == "katalog-2"


@requires_database
async def test_project_rejects_equal_languages(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.post(
        "/projects",
        headers=account.headers,
        json={"name": "Заметки", "source_language": "ru", "target_language": "ru"},
    )

    assert response.status_code == 422


@requires_database
async def test_project_name_must_look_like_a_name(db_client: AsyncClient) -> None:
    """Прижатая клавиша — не название: карточку такое слово рвёт."""
    account = await register(db_client)

    for name in ("ф" * 41, "x" * 121, " ".join(["слово"] * 30)):
        response = await db_client.post(
            "/projects",
            headers=account.headers,
            json={"name": name, "source_language": "en", "target_language": "ru"},
        )

        assert response.status_code == 422, name

    fine = await db_client.post(
        "/projects",
        headers=account.headers,
        json={"name": "  Документация   к API  ", "source_language": "en", "target_language": "ru"},
    )

    assert fine.status_code == 201, fine.text
    # Лишние пробелы схлопнуты: название хранится так, как его покажут.
    assert fine.json()["name"] == "Документация к API"


@requires_database
async def test_project_is_deleted_with_its_books(db_client: AsyncClient) -> None:
    """Проект уносит книги: их не должно остаться ни в списке, ни в хранилище."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", b"Open the valve.\n", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    removed = await db_client.delete(f"/projects/{project_id}", headers=account.headers)

    assert removed.status_code == 204, removed.text
    assert (
        await db_client.get(f"/projects/{project_id}", headers=account.headers)
    ).status_code == 404
    assert (
        await db_client.get(f"/documents/{document_id}", headers=account.headers)
    ).status_code == 404
    assert (await db_client.get("/documents", headers=account.headers)).json() == []


@requires_database
async def test_project_with_a_running_translation_is_kept(db_client: AsyncClient) -> None:
    """Рабочий держит задание и пишет в сегменты — удалять их из-под него нельзя."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", b"Open the valve.\n", "text/plain")},
    )
    document_id = uploaded.json()["id"]
    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)
    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    assert queued.status_code == 201, queued.text

    removed = await db_client.delete(f"/projects/{project_id}", headers=account.headers)

    assert removed.status_code == 409
    assert "перевод" in removed.json()["detail"]


@requires_database
async def test_foreign_project_cannot_be_deleted(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")

    removed = await db_client.delete(f"/projects/{project_id}", headers=stranger.headers)

    assert removed.status_code == 404
    assert (
        await db_client.get(f"/projects/{project_id}", headers=owner.headers)
    ).status_code == 200


@requires_database
async def test_foreign_project_is_invisible(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)

    stranger = await register(
        db_client, email="stranger@example.com", organization_name="Другая контора"
    )

    response = await db_client.get(f"/projects/{project_id}", headers=stranger.headers)

    # Именно 404, а не 403: «доступ запрещён» подтвердил бы, что проект с
    # таким идентификатором существует.
    assert response.status_code == 404

    listing = await db_client.get("/projects", headers=stranger.headers)
    assert listing.status_code == 200
    assert listing.json() == []
