"""Сводка кабинета.

Проверяется то, ради чего она собирается на стороне API: числа сходятся с
состоянием документов, очередь замечаний непустая там, где есть замечания,
и чужое рабочее пространство в сводку не попадает.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import register
from tests.test_terminology import prepare


@requires_database
async def test_empty_workspace_is_zeroes(db_client: AsyncClient) -> None:
    """Пустое пространство — это нули, а не отсутствие ответа."""
    account = await register(db_client)

    response = await db_client.get("/overview", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["projects"] == 0
    assert body["documents"] == 0
    assert body["segments"] == 0
    assert body["recent_documents"] == []
    assert body["usage"]["input_tokens"] == 0
    # Заглушка ничего не стоит, а модель не из прейскуранта — неизвестно
    # сколько; ноль в обоих случаях был бы враньём.
    assert body["usage"]["estimated_usd"] is None


@requires_database
async def test_overview_counts_the_work(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    translated = await db_client.post(
        f"/documents/{document_id}/translate?ignore_terminology=true", headers=account.headers
    )
    assert translated.status_code == 200, translated.text

    response = await db_client.get("/overview", headers=account.headers)
    body = response.json()

    assert body["projects"] == 1
    assert body["documents"] == 1
    assert body["segments"] > 0
    assert body["segments_by_status"]["machine"] > 0

    card = body["recent_documents"][0]
    assert card["title"]
    assert card["segments"] == body["segments"]
    # Готовность считается по принятому человеком: машинный перевод сам по
    # себе готовым не является.
    assert card["ready_percent"] == 0


@requires_database
async def test_findings_reach_the_queue(db_client: AsyncClient) -> None:
    """Очередь замечаний — главный экран работы, и она должна наполняться."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "Check Valve",
            "target_term": "обратный клапан",
            "source_language": "en",
            "target_language": "ru",
            "status": "confirmed",
        },
    )

    document_id = await prepare(db_client, account)
    await db_client.post(
        f"/documents/{document_id}/translate?ignore_terminology=true", headers=account.headers
    )

    body = (await db_client.get("/overview", headers=account.headers)).json()

    assert body["flagged"] > 0
    finding = body["recent_findings"][0]
    assert finding["document_title"]
    assert "glossary" in finding["checks"]


@requires_database
async def test_terminology_backlog_is_visible(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    await db_client.post(f"/documents/{document_id}/terminology/extract", headers=account.headers)

    body = (await db_client.get("/overview", headers=account.headers)).json()

    # Нерешённые термины останавливают перевод — в кабинете это должно быть
    # видно до того, как человек упрётся в отказ.
    assert body["undecided_terms"] > 0


@requires_database
async def test_overview_is_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    await prepare(db_client, owner)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    body = (await db_client.get("/overview", headers=stranger.headers)).json()

    assert body["documents"] == 0
    assert body["projects"] == 0


@requires_database
async def test_overview_needs_a_token(db_client: AsyncClient) -> None:
    response = await db_client.get("/overview")

    assert response.status_code == 401
