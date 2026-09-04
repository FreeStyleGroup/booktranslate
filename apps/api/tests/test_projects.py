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
