"""Управление доступом на площадке.

Проверяется то, ради чего это заведено: регистрация не пускает внутрь,
доступ открывает и закрывает администратор, закрытый доступ прекращает
работу немедленно, а выданный пароль действительно работает.
"""

from httpx import AsyncClient, Response

from tests.conftest import requires_database
from tests.factories import PASSWORD, admin_headers, find_user, register

APPLICANT = {
    "email": "applicant@example.com",
    "password": PASSWORD,
    "full_name": "Иван Заявкин",
    "organization_name": "Новое бюро",
}


async def apply(client: AsyncClient, **overrides: str) -> str:
    """Подать заявку и вернуть её номер.

    Номер берётся из списка администратора, а не из ответа: ответ на
    регистрацию одинаков для свободной и занятой почты и потому не содержит
    ничего опознавательного. Живой администратор находит заявку так же.
    """
    response = await client.post("/auth/register", json={**APPLICANT, **overrides})
    assert response.status_code == 202, response.text

    return await find_user(client, overrides.get("email", str(APPLICANT["email"])))


async def set_status(client: AsyncClient, user_id: str, status: str) -> Response:
    return await client.patch(
        f"/admin/users/{user_id}/status",
        headers=await admin_headers(client),
        json={"status": status},
    )


@requires_database
async def test_registration_is_only_a_request(db_client: AsyncClient) -> None:
    """Регистрация не пускает внутрь: иначе одобрение — формальность."""
    await apply(db_client)

    entered = await db_client.post(
        "/auth/login", json={"email": APPLICANT["email"], "password": PASSWORD}
    )

    assert entered.status_code == 403
    assert "не одобрена" in entered.json()["detail"]


@requires_database
async def test_wrong_password_does_not_reveal_the_state(db_client: AsyncClient) -> None:
    """До верного пароля состояние — подсказка перебирающему, а не ответ."""
    await apply(db_client)

    response = await db_client.post(
        "/auth/login", json={"email": APPLICANT["email"], "password": "not-the-password"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Неверная почта или пароль"


@requires_database
async def test_approval_opens_the_door(db_client: AsyncClient) -> None:
    applicant = await apply(db_client)

    approved = await set_status(db_client, applicant, "active")

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "active"
    # Видно, кто открыл доступ: иначе список отвечает на «кто закрыт», но
    # не на «кто закрыл».
    assert body["status_changed_by"] is not None
    assert body["organizations"] == ["Новое бюро"]

    entered = await db_client.post(
        "/auth/login", json={"email": APPLICANT["email"], "password": PASSWORD}
    )
    assert entered.status_code == 200, entered.text


@requires_database
async def test_suspension_stops_work_at_once(db_client: AsyncClient) -> None:
    """Иначе «доступ закрыт» означало бы «закрыт, когда истечёт токен»."""
    account = await register(db_client, email="worker@example.com")

    me = await db_client.get("/auth/me", headers=account.headers)
    assert me.status_code == 200

    suspended = await set_status(db_client, str(account.user_id), "suspended")
    assert suspended.status_code == 200, suspended.text

    after = await db_client.get("/auth/me", headers=account.headers)
    assert after.status_code == 401

    again = await db_client.post(
        "/auth/login", json={"email": "worker@example.com", "password": PASSWORD}
    )
    assert again.status_code == 403
    assert "приостановлен" in again.json()["detail"]


@requires_database
async def test_suspension_revokes_refresh_sessions(db_client: AsyncClient) -> None:
    applicant = await apply(db_client)
    await set_status(db_client, applicant, "active")

    entered = await db_client.post(
        "/auth/login", json={"email": APPLICANT["email"], "password": PASSWORD}
    )
    refresh_token = entered.json()["refresh_token"]

    await set_status(db_client, applicant, "suspended")

    response = await db_client.post("/auth/refresh", json={"refresh_token": refresh_token})

    # Токен обновления погашен вместе с доступом: без этого отключённый
    # человек продлевал бы себе сессию сколько угодно.
    assert response.status_code in (401, 403)


@requires_database
async def test_restored_access_works_again(db_client: AsyncClient) -> None:
    applicant = await apply(db_client)
    await set_status(db_client, applicant, "active")
    await set_status(db_client, applicant, "suspended")

    restored = await set_status(db_client, applicant, "active")
    assert restored.status_code == 200

    entered = await db_client.post(
        "/auth/login", json={"email": APPLICANT["email"], "password": PASSWORD}
    )
    assert entered.status_code == 200, entered.text


@requires_database
async def test_pending_cannot_be_restored_as_state(db_client: AsyncClient) -> None:
    """Решение уже принято, и делать вид, что его не было, — врать журналу."""
    applicant = await apply(db_client)

    response = await set_status(db_client, applicant, "pending")

    assert response.status_code == 400


@requires_database
async def test_admin_cannot_lock_himself_out(db_client: AsyncClient) -> None:
    """Закрыв доступ единственному администратору, площадку не откроет никто."""
    headers = await admin_headers(db_client)
    me = await db_client.get("/auth/me", headers=headers)
    admin_id = me.json()["user"]["id"]

    response = await set_status(db_client, admin_id, "suspended")

    assert response.status_code == 409


@requires_database
async def test_list_shows_who_and_when(db_client: AsyncClient) -> None:
    await apply(db_client)
    await register(db_client, email="worker@example.com")

    response = await db_client.get("/admin/users", headers=await admin_headers(db_client))

    assert response.status_code == 200, response.text
    body = response.json()

    by_email = {item["email"]: item for item in body["items"]}
    applicant = by_email[APPLICANT["email"]]

    assert applicant["status"] == "pending"
    assert applicant["created_at"] is not None
    assert applicant["last_login_at"] is None
    # Вошедший пользователь отличается от неспрашивавшего доступ именно
    # этим — по нему потом чистят список.
    assert by_email["worker@example.com"]["last_login_at"] is not None

    # Ожидающие идут первыми: список открывают ради них.
    assert body["items"][0]["status"] == "pending"
    assert body["counts"]["pending"] == 1


@requires_database
async def test_list_filters_by_status(db_client: AsyncClient) -> None:
    await apply(db_client)
    await register(db_client, email="worker@example.com")

    response = await db_client.get(
        "/admin/users?status=pending", headers=await admin_headers(db_client)
    )

    assert [item["email"] for item in response.json()["items"]] == [APPLICANT["email"]]


@requires_database
async def test_list_finds_by_email_part(db_client: AsyncClient) -> None:
    await apply(db_client)

    response = await db_client.get(
        "/admin/users?query=applic", headers=await admin_headers(db_client)
    )

    assert len(response.json()["items"]) == 1


@requires_database
async def test_admin_creates_user_with_generated_password(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/admin/users",
        headers=await admin_headers(db_client),
        json={
            "email": "Colleague@Example.com",
            "full_name": "Пётр Коллегин",
            "organization_name": "Отдел переводов",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()

    # Заведённая администратором запись сразу действующая: одобрять
    # собственное решение второй раз незачем.
    assert body["user"]["status"] == "active"
    assert body["organization_name"] == "Отдел переводов"
    assert len(body["password"]) >= 12

    # Пароль показывается один раз — и он должен работать.
    entered = await db_client.post(
        "/auth/login", json={"email": "colleague@example.com", "password": body["password"]}
    )
    assert entered.status_code == 200, entered.text


@requires_database
async def test_created_user_can_be_added_to_existing_workspace(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.post(
        "/admin/users",
        headers=await admin_headers(db_client),
        json={
            "email": "second@example.com",
            "organization_id": str(account.organization_id),
            "role": "translator",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == str(account.organization_id)


@requires_database
async def test_duplicate_email_is_refused(db_client: AsyncClient) -> None:
    await register(db_client, email="taken@example.com")

    response = await db_client.post(
        "/admin/users",
        headers=await admin_headers(db_client),
        json={"email": "taken@example.com", "organization_name": "Ещё одно"},
    )

    assert response.status_code == 409


@requires_database
async def test_ordinary_user_is_not_an_admin(db_client: AsyncClient) -> None:
    """Владелец своей организации не решает, кого пускать в чужие."""
    account = await register(db_client)

    listing = await db_client.get("/admin/users", headers=account.headers)
    creation = await db_client.post(
        "/admin/users",
        headers=account.headers,
        json={"email": "sneaky@example.com", "organization_name": "Чужое"},
    )

    assert listing.status_code == 403
    assert creation.status_code == 403


@requires_database
async def test_admin_section_needs_a_token(db_client: AsyncClient) -> None:
    response = await db_client.get("/admin/users")

    assert response.status_code == 401
