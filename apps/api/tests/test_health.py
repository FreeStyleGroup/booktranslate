"""Проверки живости.

`/health` проверяется без базы — он и в приложении её не трогает.
Готовность (`/health/ready`) базу трогает, поэтому идёт на клиенте с
подключённой базой и пропускается там, где её нет.
"""

from httpx import AsyncClient

from tests.conftest import requires_database


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@requires_database
async def test_ready_reports_database(db_client: AsyncClient) -> None:
    response = await db_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
