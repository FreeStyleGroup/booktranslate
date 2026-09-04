"""Проверки живости.

`/health` проверяется без базы — он и в приложении её не трогает.
Готовность (`/health/ready`) проверяется отдельным тестом, который нужен
поднятый Postgres, поэтому он помечен и по умолчанию пропускается.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def client() -> AsyncClient:
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_returns_ok(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.skipif(
    os.getenv("DATABASE_URL") is None,
    reason="нужен доступ к базе: запускается в docker compose",
)
async def test_ready_reports_database(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health/ready")

    assert response.status_code in (200, 503)
    assert response.json()["status"] in ("ready", "unavailable")
