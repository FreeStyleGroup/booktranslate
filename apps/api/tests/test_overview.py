"""Сводка кабинета.

Проверяется то, ради чего она собирается на стороне API: числа сходятся с тем, что на
самом деле переведено, сорвавшееся видно, и чужое рабочее пространство в сводку не
попадает.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker as worker_module
from app.models.translation import TranslationRun
from app.services.providers import ProviderError, StubProvider, Translated, TranslationRequest
from tests.chapters import open_book, translate, translated_book, uploaded_book
from tests.conftest import requires_database
from tests.factories import register

MANUAL = b"Open the valve before start.\n\nCheck the pressure gauge.\n\n12,5\n"


@requires_database
async def test_overview_prices_a_real_translation(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """🔥 Сумму токенов Postgres отдаёт как Decimal; прейскурант умножает на float.

    Пока расход нулевой, ошибка не проявляется — первая переведённая книга роняла сводку
    целиком, и кабинет открывался пустым.
    """
    account = await register(db_client)
    await translated_book(db_client, session, account, data=MANUAL)

    run = await session.scalar(select(TranslationRun).limit(1))
    assert run is not None
    run.model = "claude-opus-5"
    run.input_tokens = 1000
    run.output_tokens = 500
    run.cached_input_tokens = 100
    run.cache_write_tokens = 50
    await session.commit()

    response = await db_client.get("/overview", headers=account.headers)

    assert response.status_code == 200, response.text
    usage = response.json()["usage"]
    assert usage["input_tokens"] == 1000
    assert usage["estimated_usd"] is not None and usage["estimated_usd"] > 0


@requires_database
async def test_empty_workspace_is_zeroes(db_client: AsyncClient) -> None:
    """Пустое пространство — это нули, а не отсутствие ответа."""
    account = await register(db_client)

    response = await db_client.get("/overview", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["projects"] == 0
    assert body["books"] == 0
    assert body["blocks"] == 0
    assert body["recent_books"] == []
    assert body["usage"]["input_tokens"] == 0
    # Заглушка ничего не стоит, а модель не из прейскуранта стоит неизвестно сколько;
    # ноль в обоих случаях был бы враньём.
    assert body["usage"]["estimated_usd"] is None


@requires_database
async def test_overview_counts_the_work(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    await translated_book(db_client, session, account, data=MANUAL)

    body = (await db_client.get("/overview", headers=account.headers)).json()

    assert body["projects"] == 1
    assert body["books"] == 1
    assert body["documents"] == 1
    assert body["blocks"] == 3
    assert body["translated"] == 3
    assert body["by_origin"] == {"model": 2, "copy": 1}
    assert body["live_runs"] == 0

    card = body["recent_books"][0]
    assert card["title"] == "Manual"
    assert card["blocks"] == 3
    assert card["ready_percent"] == 100


@requires_database
async def test_live_run_is_visible(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)

    started = await db_client.post(
        f"/chapters/{book.chapter}/translation", headers=account.headers, json={}
    )
    assert started.status_code == 201, started.text

    body = (await db_client.get("/overview", headers=account.headers)).json()

    assert body["live_runs"] == 1
    assert body["translated"] == 0


@requires_database
async def test_rejected_blocks_reach_attention(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Блок без перевода — то, за чем человек открывает кабинет."""

    class Refusing(StubProvider):
        async def translate(self, requests: list[TranslationRequest]) -> Translated:
            if any("Open" in request.source_text for request in requests):
                raise ProviderError("Модель отказалась переводить эту пачку")

            return await super().translate(requests)

    monkeypatch.setattr(worker_module, "get_provider", lambda _model=None: Refusing())

    account = await register(db_client)
    book = await open_book(db_client, account, data=MANUAL)
    await translate(db_client, session, account, book.chapter)

    body = (await db_client.get("/overview", headers=account.headers)).json()

    assert body["translated"] == 2
    [card] = body["attention"]
    assert card["chapter_id"] == book.chapter
    assert "Без перевода" in card["problem"]


@requires_database
async def test_terminology_backlog_is_visible(db_client: AsyncClient) -> None:
    account = await register(db_client)
    book = await uploaded_book(
        db_client,
        account,
        data=b"Open the check valve.\n\nClose the check valve.\n\nThe check valve leaks.\n",
    )
    extracted = await db_client.post(
        f"/chapters/{book.chapter}/masters", headers=account.headers, json={"reason": None}
    )
    assert extracted.status_code == 201, extracted.text

    await db_client.post(f"/chapters/{book.chapter}/terminology/extract", headers=account.headers)

    body = (await db_client.get("/overview", headers=account.headers)).json()

    # Нерешённые термины останавливают перевод — это видно до того, как человек упрётся
    # в отказ.
    assert body["undecided_terms"] > 0


@requires_database
async def test_overview_is_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    await open_book(db_client, owner, data=MANUAL)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    body = (await db_client.get("/overview", headers=stranger.headers)).json()

    assert body["books"] == 0
    assert body["projects"] == 0
    assert body["blocks"] == 0


@requires_database
async def test_overview_needs_a_token(db_client: AsyncClient) -> None:
    response = await db_client.get("/overview")

    assert response.status_code == 401
