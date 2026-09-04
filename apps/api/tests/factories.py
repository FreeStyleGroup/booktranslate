"""Заготовки для тестов: зарегистрированный пользователь и его проект.

Каждый тест идёт в транзакции, которая откатывается, поэтому одинаковые
почты в разных тестах не конфликтуют и специально разводить их не нужно.
"""

import io
import uuid
import zipfile

from httpx import AsyncClient


class Account:
    """Зарегистрированный пользователь: заголовки, он сам и его организация."""

    def __init__(
        self, headers: dict[str, str], user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        self.headers = headers
        self.user_id = user_id
        self.organization_id = organization_id

    def headers_for(self, organization_id: uuid.UUID) -> dict[str, str]:
        """Заголовки для работы в указанной организации."""
        return {**self.headers, "X-Organization-Id": str(organization_id)}


async def register(
    client: AsyncClient,
    *,
    email: str = "owner@example.com",
    organization_name: str = "Бюро переводов",
) -> Account:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery",
            "full_name": "Владелец",
            "organization_name": organization_name,
        },
    )
    assert response.status_code == 201, response.text

    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()

    return Account(
        headers=headers,
        user_id=uuid.UUID(body["user"]["id"]),
        organization_id=uuid.UUID(body["memberships"][0]["organization_id"]),
    )


async def create_project(
    client: AsyncClient, account: Account, *, name: str = "Руководство по эксплуатации"
) -> str:
    response = await client.post(
        "/projects",
        headers=account.headers,
        json={"name": name, "source_language": "en", "target_language": "ru"},
    )
    assert response.status_code == 201, response.text

    project_id: str = response.json()["id"]
    return project_id


def docx_bytes(text: str = "Раздел первый") -> bytes:
    """Минимальный DOCX: ZIP с обязательной частью `word/document.xml`.

    Настоящий Word кладёт туда куда больше, но определение формата смотрит
    именно на эту часть, и подделывать остальное ради теста незачем.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<document><p>{text}</p></document>")

    return buffer.getvalue()
