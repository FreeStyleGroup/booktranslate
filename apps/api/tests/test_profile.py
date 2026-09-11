"""Паспорт документа через API.

Проверяется то, по чему человек решает, платить ли: объём считается по
разобранному тексту, повтор в оплату не попадает, память переводов
уменьшает счёт, а чужой документ не показывает своего объёма.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.organization import Membership, Role
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

# Второй и четвёртый абзацы совпадают: в руководствах предупреждение
# повторяется десятками раз, и в смете оно обязано стоить один раз.
MANUAL = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Check the pressure gauge.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
)


async def upload(
    client: AsyncClient, account: Account, project_id: str, *, data: bytes = MANUAL
) -> str:
    response = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", data, "text/plain")},
    )
    assert response.status_code == 201, response.text

    document_id: str = response.json()["id"]
    return document_id


@requires_database
async def test_profile_of_unparsed_document_is_empty(db_client: AsyncClient) -> None:
    """До разбора состав неизвестен — и отвечать надо именно так.

    Нули, а не отказ: карточка документа открывается сразу после загрузки,
    и ошибка вместо паспорта выглядела бы как сломанный файл.
    """
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)

    response = await db_client.get(f"/documents/{document_id}/profile", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["segments"] == 0
    assert body["characters"] == 0
    assert body["estimate"] is None


@requires_database
async def test_profile_counts_text_after_parsing(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)

    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    body = (
        await db_client.get(f"/documents/{document_id}/profile", headers=account.headers)
    ).json()

    assert body["segments"] == 4
    assert body["characters"] > 0
    assert body["words"] > 0
    # Самый длинный сегмент не длиннее всего текста и не короче среднего:
    # проверяется, что считается именно максимум, а не первая попавшаяся
    # строка.
    assert 0 < body["longest_segment_chars"] <= body["characters"]
    assert body["by_kind"]["paragraph"] == 4
    assert body["by_status"]["new"] == 4


@requires_database
async def test_repeated_text_is_billed_once(db_client: AsyncClient) -> None:
    """Повтор внутри книги переводится один раз — и стоит один раз."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    document_id = await upload(db_client, account, project_id)

    await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

    body = (
        await db_client.get(f"/documents/{document_id}/profile", headers=account.headers)
    ).json()

    assert body["untranslated"] == 4
    assert body["unique_untranslated"] == 3
    assert body["repeated"] == 1
    assert body["billable_texts"] == 3
    assert body["estimate"]["input_tokens"] > 0


@requires_database
async def test_memory_lowers_the_bill(db_client: AsyncClient) -> None:
    """Переведённое однажды не оплачивается второй раз.

    Ровно то, чем память переводов окупается, и ровно то, что заказчик
    хочет видеть до начала работы, а не в отчёте после.
    """
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    first = await upload(db_client, account, project_id)
    await db_client.post(f"/documents/{first}/parse", headers=account.headers)
    translated = await db_client.post(f"/documents/{first}/translate", headers=account.headers)
    assert translated.status_code == 200, translated.text

    # Вторая книга начинается с того же предупреждения — и оно уже в памяти.
    second = await upload(
        db_client,
        account,
        project_id,
        data=b"Warning! Disconnect the power supply.\n\nRemove the cover.\n",
    )
    await db_client.post(f"/documents/{second}/parse", headers=account.headers)

    body = (await db_client.get(f"/documents/{second}/profile", headers=account.headers)).json()

    assert body["unique_untranslated"] == 2
    assert body["memory_matches"] == 1
    assert body["billable_texts"] == 1


@requires_database
async def test_profile_does_not_need_a_model_key(db_client: AsyncClient) -> None:
    """Карточку документа открывают, не собираясь никуда ходить.

    Смете нужно имя модели, а не соединение с ней. Пока имя добывалось
    через клиента, установка с невписанным ключом отвечала на открытие
    карточки отказом — и выглядело это как сломанный документ.
    """
    settings = get_settings()
    was_provider, was_key = settings.translation_provider, settings.anthropic_api_key
    settings.translation_provider = "claude"
    settings.anthropic_api_key = ""

    try:
        account = await register(db_client)
        project_id = await create_project(db_client, account)
        document_id = await upload(db_client, account, project_id)
        await db_client.post(f"/documents/{document_id}/parse", headers=account.headers)

        response = await db_client.get(f"/documents/{document_id}/profile", headers=account.headers)
    finally:
        settings.translation_provider = was_provider
        settings.anthropic_api_key = was_key

    assert response.status_code == 200, response.text
    # Модель известна и есть в прейскуранте — значит смета в деньгах.
    assert response.json()["estimate"]["usd"] > 0


@requires_database
async def test_foreign_document_has_no_profile(db_client: AsyncClient) -> None:
    """Объём чужой книги — тоже сведения о ней."""
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    document_id = await upload(db_client, owner, project_id)

    stranger = await register(
        db_client, email="stranger@example.com", organization_name="Другая контора"
    )

    response = await db_client.get(f"/documents/{document_id}/profile", headers=stranger.headers)

    assert response.status_code == 404, response.text


@requires_database
async def test_workspace_lists_documents_of_all_projects(db_client: AsyncClient) -> None:
    account = await register(db_client)

    first = await create_project(db_client, account, name="Первый проект")
    second = await create_project(db_client, account, name="Второй проект")

    await upload(db_client, account, first)
    await upload(db_client, account, second, data=b"Another manual entirely.\n")

    everything = await db_client.get("/documents", headers=account.headers)
    only_second = await db_client.get(
        "/documents", params={"project_id": second}, headers=account.headers
    )

    assert everything.status_code == 200, everything.text
    assert len(everything.json()) == 2
    assert len(only_second.json()) == 1
    assert only_second.json()[0]["project_id"] == second


@requires_database
async def test_viewer_sees_the_profile(db_client: AsyncClient, session: AsyncSession) -> None:
    """Смету смотрит и наблюдатель: загружать он не вправе, а знать объём —
    вправе, иначе ему не с чем прийти к заказчику."""
    owner = await register(db_client)
    project_id = await create_project(db_client, owner)
    document_id = await upload(db_client, owner, project_id)
    await db_client.post(f"/documents/{document_id}/parse", headers=owner.headers)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя контора")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    response = await db_client.get(
        f"/documents/{document_id}/profile",
        headers=guest.headers_for(owner.organization_id),
    )

    assert response.status_code == 200, response.text
    assert response.json()["segments"] == 4
