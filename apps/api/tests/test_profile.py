"""Смета главы и список файлов пространства.

Проверяется то, ради чего смета заведена: цену видно до запуска, повторы и готовые
переводы её снижают, а защищённое не стоит ничего.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.organization import Membership, Role
from tests.chapters import open_book, translate
from tests.conftest import requires_database
from tests.factories import create_project, register
from tests.test_memory import seed

MANUAL = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Open the valve before start.\n"
    b"\n"
    b"12,5\n"
)


async def estimate(client: AsyncClient, headers: dict[str, str], chapter_id: str) -> dict:
    response = await client.get(f"/chapters/{chapter_id}/translation/estimate", headers=headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


@requires_database
async def test_estimate_counts_the_chapter(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)

    body = await estimate(db_client, account.headers, book.chapter)

    assert body["blocks"] == 4
    assert body["characters"] > 0
    assert body["words"] > 0
    assert body["longest_block_chars"] == len("Warning! Disconnect the power supply.")
    assert body["by_kind"]
    assert body["untranslated"] == 4


@requires_database
async def test_protected_and_repeated_are_not_billed(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)

    body = await estimate(db_client, account.headers, book.chapter)

    assert body["protected"] == 1
    assert body["repeated"] == 1
    assert body["unique_untranslated"] == 2
    assert body["billable_texts"] == 2
    assert body["billable_characters"] == len("Open the valve before start.") + len(
        "Warning! Disconnect the power supply."
    )


@requires_database
async def test_memory_lowers_the_bill(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    await seed(session, account, [("Open the valve before start.", "Откройте клапан.")])
    book = await open_book(db_client, account, data=MANUAL)

    body = await estimate(db_client, account.headers, book.chapter)

    assert body["memory_matches"] == 1
    assert body["billable_texts"] == 1


@requires_database
async def test_translation_in_the_book_lowers_the_bill(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Текст уже переведён в другой главе — платить за него второй раз незачем."""
    account = await register(db_client)
    book = await open_book(
        db_client,
        account,
        data=b"# One\n\nCheck the valve daily.\n\n# Two\n\nCheck the valve daily.\n\nFresh text.\n",
        name="manual.md",
        media="text/markdown",
    )
    assert len(book.chapters) == 2

    await translate(db_client, session, account, book.chapters[0])

    body = await estimate(db_client, account.headers, book.chapters[1])

    assert body["book_matches"] == 1
    assert body["billable_texts"] == 2


@requires_database
async def test_translated_chapter_has_nothing_to_pay_for(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)
    await translate(db_client, session, account, book.chapter)

    body = await estimate(db_client, account.headers, book.chapter)

    assert body["untranslated"] == 0
    assert body["billable_characters"] == 0
    assert body["estimate"] is None


@requires_database
async def test_estimate_does_not_need_a_model_key(db_client: AsyncClient) -> None:
    """Смете нужно имя модели, а не клиент: иначе отказ на установке без ключа."""
    settings = get_settings()
    provider, key = settings.translation_provider, settings.anthropic_api_key
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)

    settings.translation_provider = "claude"
    settings.anthropic_api_key = ""

    try:
        body = await estimate(db_client, account.headers, book.chapter)
    finally:
        settings.translation_provider = provider
        settings.anthropic_api_key = key

    assert body["estimate"] is not None
    assert body["estimate"]["usd"] is not None


@requires_database
async def test_foreign_chapter_has_no_estimate(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    book = await open_book(db_client, owner, data=MANUAL)
    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    response = await db_client.get(
        f"/chapters/{book.chapter}/translation/estimate", headers=stranger.headers
    )

    assert response.status_code == 404, response.text


@requires_database
async def test_viewer_sees_the_estimate(db_client: AsyncClient, session: AsyncSession) -> None:
    """Смету смотрит и наблюдатель: иначе ему не с чем прийти к заказчику."""
    owner = await register(db_client)
    book = await open_book(db_client, owner, data=MANUAL)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    body = await estimate(db_client, guest.headers_for(owner.organization_id), book.chapter)

    assert body["blocks"] == 4


@requires_database
async def test_workspace_lists_documents_of_all_projects(db_client: AsyncClient) -> None:
    account = await register(db_client)

    first = await create_project(db_client, account, name="Первый проект")
    second = await create_project(db_client, account, name="Второй проект")

    for project, data in ((first, MANUAL), (second, b"Another manual entirely.\n")):
        uploaded = await db_client.post(
            f"/projects/{project}/documents",
            headers=account.headers,
            files={"file": ("manual.txt", data, "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text

    everything = await db_client.get("/documents", headers=account.headers)
    only_second = await db_client.get(
        "/documents", params={"project_id": second}, headers=account.headers
    )

    assert everything.status_code == 200, everything.text
    assert len(everything.json()) == 2
    assert len(only_second.json()) == 1
    assert only_second.json()[0]["project_id"] == second
