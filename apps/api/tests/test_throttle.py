"""Ограничение частоты запросов.

Проверяется на приложении со своими настройками: в общем наборе потолок
поднят до недостижимого, иначе половина тестов падала бы отказом «слишком
часто» — они и есть десяток запросов подряд с одного адреса.

База здесь не нужна: отказ выдаётся до обработчика, и до неё дело не
доходит.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
async def strict_client() -> AsyncGenerator[AsyncClient]:
    settings = get_settings()
    general, guarded = settings.rate_limit_per_minute, settings.auth_rate_limit_per_minute

    settings.rate_limit_per_minute = 3
    settings.auth_rate_limit_per_minute = 2

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        yield client

    settings.rate_limit_per_minute = general
    settings.auth_rate_limit_per_minute = guarded


async def test_login_is_capped_harder_than_the_rest(strict_client: AsyncClient) -> None:
    """Вход считается Argon2id и по замыслу дорог.

    Без отдельной, строгой меры десяток одновременных запросов с любым
    паролем занимает всю память и весь процессор — сервер ложится, не
    пропустив ни одного настоящего пользователя.
    """
    # Тело намеренно неполное: разбор схемы отвергает его раньше обращения
    # к базе, а ограничитель считает попытки до разбора — значит проверка
    # обходится без Postgres и меряет ровно то, что нужно.
    body = {"email": "someone@example.com"}

    first = await strict_client.post("/auth/login", json=body)
    second = await strict_client.post("/auth/login", json=body)
    third = await strict_client.post("/auth/login", json=body)

    assert first.status_code == 422
    assert second.status_code == 422
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"


async def test_general_paths_have_their_own_counter(strict_client: AsyncClient) -> None:
    """Счётчик входа не расходуется обычными запросами, и наоборот."""
    for _ in range(3):
        assert (await strict_client.get("/health")).status_code == 200

    assert (await strict_client.get("/health")).status_code == 429

    # Вход считается отдельно и своей мерой — исчерпанный общий счётчик его
    # не закрывает.
    assert (
        await strict_client.post("/auth/login", json={"email": "a@example.com"})
    ).status_code == 422
