"""Издание и комплект исходников: коды, роли, изоляция, журнал решений."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.organization import Membership, Role
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

MANUAL = "Руководство по эксплуатации.\n\nПервый раздел.".encode()
APPENDIX = "Приложение A. Таблицы.".encode()


async def upload(
    client: AsyncClient, account: Account, project_id: str, *, name: str, body: bytes
) -> str:
    response = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": (name, body, "text/plain")},
    )
    assert response.status_code == 201, response.text

    document_id: str = response.json()["id"]
    return document_id


async def create_book(
    client: AsyncClient, account: Account, project_id: str, *, title: str = "Машинное обучение"
) -> dict[str, str]:
    response = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": title}
    )
    assert response.status_code == 201, response.text

    book: dict[str, str] = response.json()
    return book


@requires_database
async def test_book_gets_code_and_pair_from_project(db_client: AsyncClient) -> None:
    """Код выдаёт сервер, языковая пара наследуется от проекта."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    first = await create_book(db_client, account, project_id)
    second = await create_book(db_client, account, project_id, title="Второй том")

    assert first["code"] == "BK01"
    # Номер не повторяется: он уходит в номера замечаний, и две книги с
    # одним кодом сделали бы реестр ошибок бессмысленным.
    assert second["code"] == "BK02"
    assert (first["source_language"], first["target_language"]) == ("en", "ru")
    assert first["status"] == "draft"


@requires_database
async def test_list_sorts_and_pages_on_the_server(db_client: AsyncClient) -> None:
    """Порядок и страница — дело запроса: в браузере сортируется только выданное."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    for title in ("Бета", "Альфа", "Гамма"):
        await create_book(db_client, account, project_id, title=title)

    by_title = await db_client.get("/books?sort=title&order=asc&limit=2", headers=account.headers)
    assert by_title.status_code == 200, by_title.text
    page = by_title.json()

    # Общее число — по всему отбору, а не по выданной странице: иначе на
    # экране не посчитать номера страниц.
    assert page["total"] == 3
    assert [book["title"] for book in page["items"]] == ["Альфа", "Бета"]

    tail = await db_client.get(
        "/books?sort=title&order=asc&limit=2&offset=2", headers=account.headers
    )
    assert [book["title"] for book in tail.json()["items"]] == ["Гамма"]

    # По умолчанию — последние заведённые первыми.
    newest = await db_client.get("/books", headers=account.headers)
    assert [book["code"] for book in newest.json()["items"]] == ["BK03", "BK02", "BK01"]


@requires_database
async def test_unknown_sort_is_rejected(db_client: AsyncClient) -> None:
    """Столбец приходит перечислением: подставить в «ORDER BY» своё нельзя."""
    account = await register(db_client)

    response = await db_client.get("/books?sort=id", headers=account.headers)

    assert response.status_code == 422


@requires_database
async def test_book_is_invisible_to_another_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    book = await create_book(db_client, owner, project_id)

    stranger = await register(
        db_client, email="stranger@example.com", organization_name="Чужая контора"
    )

    response = await db_client.get(f"/books/{book['id']}", headers=stranger.headers)

    # Не «запрещено», а «не найдено»: 403 подтвердил бы, что такая книга есть.
    assert response.status_code == 404


@requires_database
async def test_viewer_cannot_create_book(db_client: AsyncClient, session: AsyncSession) -> None:
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя контора")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    headers = guest.headers_for(owner.organization_id)

    response = await db_client.post(
        f"/projects/{project_id}/books", headers=headers, json={"title": "Чужая книга"}
    )

    assert response.status_code == 403


@requires_database
async def test_book_keeps_one_primary_source(db_client: AsyncClient) -> None:
    """Основной источник у книги один — это держит ограничение в базе."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    book = await create_book(db_client, account, project_id)

    first = await upload(db_client, account, project_id, name="manual.txt", body=MANUAL)
    second = await upload(db_client, account, project_id, name="appendix.txt", body=APPENDIX)

    attached = await db_client.post(
        f"/books/{book['id']}/sources",
        headers=account.headers,
        json={"document_id": first, "role": "primary_text"},
    )
    assert attached.status_code == 201, attached.text

    rejected = await db_client.post(
        f"/books/{book['id']}/sources",
        headers=account.headers,
        json={"document_id": second, "role": "primary_text"},
    )

    assert rejected.status_code == 409
    assert "основной источник" in rejected.json()["detail"]


@requires_database
async def test_primary_source_changes_in_two_steps(db_client: AsyncClient) -> None:
    """Заменить основной источник можно, но решением, а не загрузкой файла."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    book = await create_book(db_client, account, project_id)

    old = await upload(db_client, account, project_id, name="draft.txt", body=MANUAL)
    new = await upload(db_client, account, project_id, name="final.txt", body=APPENDIX)

    for document_id, role in ((old, "primary_text"), (new, "auxiliary")):
        attached = await db_client.post(
            f"/books/{book['id']}/sources",
            headers=account.headers,
            json={"document_id": document_id, "role": role},
        )
        assert attached.status_code == 201, attached.text

    # Шаг первый: прежний перестаёт быть основным.
    demoted = await db_client.patch(
        f"/books/{book['id']}/sources/{old}",
        headers=account.headers,
        json={"role": "visual_reference"},
    )
    assert demoted.status_code == 200, demoted.text

    # Шаг второй: основным становится другой.
    promoted = await db_client.patch(
        f"/books/{book['id']}/sources/{new}",
        headers=account.headers,
        json={"role": "primary_text"},
    )

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["source_role"] == "primary_text"


@requires_database
async def test_document_from_another_project_is_rejected(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    other_project_id = await create_project(db_client, account, name="Другой проект")

    book = await create_book(db_client, account, project_id)
    stray = await upload(db_client, account, other_project_id, name="stray.txt", body=MANUAL)

    response = await db_client.post(
        f"/books/{book['id']}/sources",
        headers=account.headers,
        json={"document_id": stray, "role": "auxiliary"},
    )

    assert response.status_code == 409
    assert "другой проект" in response.json()["detail"]


@requires_database
async def test_file_can_be_uploaded_straight_into_the_kit(db_client: AsyncClient) -> None:
    """Загрузить и назначить роль — одним запросом, а не двумя."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    book = await create_book(db_client, account, project_id)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
        data={"book_id": book["id"], "source_role": "primary_text"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["source_role"] == "primary_text"
    assert response.json()["book_id"] == book["id"]

    kit = await db_client.get(f"/books/{book['id']}/sources", headers=account.headers)
    assert [source["id"] for source in kit.json()["sources"]] == [response.json()["id"]]


@requires_database
async def test_second_primary_is_refused_before_the_file_is_stored(db_client: AsyncClient) -> None:
    """Отказ приходит до укладки файла: в проекте он не остаётся."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    book = await create_book(db_client, account, project_id)

    for name, body in (("first.txt", MANUAL), ("second.txt", APPENDIX)):
        response = await db_client.post(
            f"/projects/{project_id}/documents",
            headers=account.headers,
            files={"file": (name, body, "text/plain")},
            data={"book_id": book["id"], "source_role": "primary_text"},
        )

        if name == "first.txt":
            assert response.status_code == 201, response.text
            continue

        assert response.status_code == 409
        assert "основной источник" in response.json()["detail"]

    # Отказанный файл в проекте не остался: до записи дело не дошло.
    documents = await db_client.get(f"/projects/{project_id}/documents", headers=account.headers)
    assert [document["original_filename"] for document in documents.json()] == ["first.txt"]


@requires_database
async def test_role_without_a_book_is_refused(db_client: AsyncClient) -> None:
    """Роль вне комплекта смысла не имеет — и запрос отклоняется."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    response = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
        data={"source_role": "primary_text"},
    )

    assert response.status_code == 400
    assert "вместе" in response.json()["detail"]


@requires_database
async def test_kit_shows_roles_and_checksums(db_client: AsyncClient) -> None:
    """Комплект показывает, из чего состоит книга: роли и контрольные суммы."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    book = await create_book(db_client, account, project_id)

    primary = await upload(db_client, account, project_id, name="book.txt", body=MANUAL)
    extra = await upload(db_client, account, project_id, name="appendix.txt", body=APPENDIX)

    for document_id, role in ((extra, "auxiliary"), (primary, "primary_text")):
        attached = await db_client.post(
            f"/books/{book['id']}/sources",
            headers=account.headers,
            json={"document_id": document_id, "role": role},
        )
        assert attached.status_code == 201, attached.text

    response = await db_client.get(f"/books/{book['id']}/sources", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    sources = body["sources"]

    assert len(sources) == 2
    # Основной источник первым, независимо от порядка добавления: на
    # экране он не должен теряться среди вспомогательных.
    assert sources[0]["id"] == primary
    assert sources[0]["source_role"] == "primary_text"
    assert all(source["content_hash"] for source in sources)
    # Файлы ещё не проверяли — и об этом сказано прямо, а не умолчанием.
    assert all(source["validation"] is None for source in sources)
    assert body["mismatch"] is None


@requires_database
async def test_decisions_are_recorded(db_client: AsyncClient, session: AsyncSession) -> None:
    """Заведение книги и назначение роли — решения, и они остаются в журнале."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    book = await create_book(db_client, account, project_id)

    document_id = await upload(db_client, account, project_id, name="book.txt", body=MANUAL)
    attached = await db_client.post(
        f"/books/{book['id']}/sources",
        headers=account.headers,
        json={"document_id": document_id, "role": "primary_text"},
    )
    assert attached.status_code == 201, attached.text

    events = list(
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.organization_id == account.organization_id)
            .order_by(AuditEvent.created_at)
        )
    )

    kinds = [event.kind for event in events]
    assert "book.created" in kinds
    assert "book.source_role_set" in kinds

    created = next(event for event in events if event.kind == "book.created")
    assert created.actor_id == account.user_id
    assert created.subject_id == uuid.UUID(book["id"])
    assert created.payload["code"] == "BK01"
