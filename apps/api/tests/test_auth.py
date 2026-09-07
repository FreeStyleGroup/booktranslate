"""Вход, регистрация и ротация токенов.

Проверяется поведение, за которое реально придётся отвечать: чужой не
входит, повторное использование токена гасит сессии, ответы не выдают,
кто здесь зарегистрирован.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import admin_headers, find_user

REGISTRATION = {
    "email": "editor@example.com",
    "password": "correct-horse-battery",
    "full_name": "Анна Редакторова",
    "organization_name": "Бюро переводов",
}


async def _register(db_client: AsyncClient, **overrides: str) -> dict[str, str]:
    """Заявка, одобрение и вход.

    Регистрация сама по себе внутрь не пускает, поэтому здесь проходится
    весь порядок: тестам ниже нужен работающий пользователь, а не
    ожидающий решения.
    """
    payload = {**REGISTRATION, **overrides}
    response = await db_client.post("/auth/register", json=payload)
    assert response.status_code == 202, response.text

    approved = await db_client.patch(
        f"/admin/users/{await find_user(db_client, payload['email'])}/status",
        headers=await admin_headers(db_client),
        json={"status": "active"},
    )
    assert approved.status_code == 200, approved.text

    entered = await db_client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert entered.status_code == 200, entered.text

    tokens: dict[str, str] = entered.json()
    return tokens


@requires_database
async def test_registration_creates_owner_of_new_organization(db_client: AsyncClient) -> None:
    tokens = await _register(db_client)

    me = await db_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert me.status_code == 200, me.text
    body = me.json()
    assert body["user"]["email"] == REGISTRATION["email"]
    # Заведение организации делает человека её владельцем: иначе первым
    # же действием оказалось бы некому выдать права.
    assert body["memberships"][0]["role"] == "owner"
    assert body["memberships"][0]["organization_name"] == REGISTRATION["organization_name"]


@requires_database
async def test_repeated_registration_does_not_reveal_the_email_is_taken(
    db_client: AsyncClient,
) -> None:
    """Ответ на занятую почту неотличим от ответа на свободную.

    Иначе форма регистрации отвечает на вопрос «работает ли здесь такой-то»,
    который вход отвечать отказывается, — и вся осторожность входа
    обесценивается соседней формой.
    """
    await _register(db_client)

    free = await db_client.post(
        "/auth/register", json={**REGISTRATION, "email": "nobody@example.com"}
    )
    taken = await db_client.post(
        "/auth/register", json={**REGISTRATION, "password": "another-password-entirely"}
    )

    assert taken.status_code == free.status_code == 202
    assert taken.json() == free.json()

    # И вторая заявка ничего не переписала: пароль остался прежним.
    entered = await db_client.post(
        "/auth/login",
        json={"email": REGISTRATION["email"], "password": "another-password-entirely"},
    )
    assert entered.status_code == 401


@requires_database
async def test_login_accepts_correct_password(db_client: AsyncClient) -> None:
    await _register(db_client)

    response = await db_client.post(
        "/auth/login",
        json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


@requires_database
async def test_login_rejects_wrong_password_without_hinting(db_client: AsyncClient) -> None:
    await _register(db_client)

    wrong_password = await db_client.post(
        "/auth/login", json={"email": REGISTRATION["email"], "password": "not-the-password"}
    )
    unknown_user = await db_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "not-the-password"}
    )

    assert wrong_password.status_code == 401
    # Ответы совпадают намеренно: по разнице между «пароль не тот» и
    # «такого нет» перебором выясняют, кто зарегистрирован.
    assert unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


@requires_database
async def test_refresh_rotates_token(db_client: AsyncClient) -> None:
    tokens = await _register(db_client)

    response = await db_client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["refresh_token"] != tokens["refresh_token"]


@requires_database
async def test_reused_refresh_token_revokes_all_sessions(db_client: AsyncClient) -> None:
    tokens = await _register(db_client)

    rotated = await db_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200

    # Повторный приход по уже использованному токену — признак кражи:
    # различить гонку клиента и злоумышленника нельзя, поэтому гасятся
    # все сессии пользователя, включая только что выданную.
    reused = await db_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401

    fresh_token = rotated.json()["refresh_token"]
    after_revocation = await db_client.post("/auth/refresh", json={"refresh_token": fresh_token})
    assert after_revocation.status_code == 401


@requires_database
async def test_logout_disables_refresh_token(db_client: AsyncClient) -> None:
    tokens = await _register(db_client)

    logout = await db_client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204

    response = await db_client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})

    assert response.status_code == 401
