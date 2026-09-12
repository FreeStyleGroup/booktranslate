"""Команда рабочего пространства и приглашения.

Проверяется то, ради чего это заведено: владелец пускает людей в своё
пространство сам, приглашённый входит без второго одобрения, а три
правила про роли не дают оставить пространство без хозяина.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Invitation
from tests.conftest import requires_database
from tests.factories import PASSWORD, Account, register

GUEST = "guest@example.com"


async def invite(
    client: AsyncClient, account: Account, *, email: str = GUEST, role: str = "translator"
) -> dict[str, object]:
    response = await client.post(
        "/team/invitations", headers=account.headers, json={"email": email, "role": role}
    )
    assert response.status_code == 201, response.text

    body: dict[str, object] = response.json()
    return body


def token_of(invited: dict[str, object]) -> str:
    link = str(invited["link"])

    return link.split("token=", 1)[1]


async def accept_as_new(
    client: AsyncClient, token: str, *, full_name: str = "Гость"
) -> dict[str, str]:
    response = await client.post(
        "/auth/invitations/accept",
        json={"token": token, "password": PASSWORD, "full_name": full_name},
    )
    assert response.status_code == 200, response.text

    entered = await client.post("/auth/login", json={"email": GUEST, "password": PASSWORD})
    assert entered.status_code == 200, entered.text

    return {"Authorization": f"Bearer {entered.json()['access_token']}"}


@requires_database
async def test_invitation_carries_a_link_and_says_whether_the_letter_went(
    db_client: AsyncClient,
) -> None:
    """Почта площадки в тестах не настроена — и ответ обязан сказать это, а не молчать."""
    owner = await register(db_client)

    invited = await invite(db_client, owner)

    assert "/join?token=" in str(invited["link"])
    assert invited["email_sent"] is False
    assert "SMTP_HOST" in str(invited["email_detail"])

    team = await db_client.get("/team", headers=owner.headers)
    invitations = team.json()["invitations"]

    assert [item["email"] for item in invitations] == [GUEST]
    assert invitations[0]["expired"] is False
    assert invitations[0]["invited_by"] == "Владелец"


@requires_database
async def test_invited_person_gets_a_working_account_without_platform_approval(
    db_client: AsyncClient,
) -> None:
    """Площадка одобрила заказчика; кого он пускает к своим книгам — его дело."""
    owner = await register(db_client)
    token = token_of(await invite(db_client, owner, role="reviewer"))

    preview = await db_client.post("/auth/invitations/lookup", json={"token": token})

    assert preview.status_code == 200, preview.text
    assert preview.json()["organization_name"] == "Бюро переводов"
    assert preview.json()["has_account"] is False

    headers = await accept_as_new(db_client, token)

    me = await db_client.get("/auth/me", headers=headers)
    memberships = me.json()["memberships"]

    assert me.json()["user"]["status"] == "active"
    assert [item["role"] for item in memberships] == ["reviewer"]
    assert memberships[0]["organization_id"] == str(owner.organization_id)

    # Ссылка одноразовая: второй раз по ней не входят.
    again = await db_client.post("/auth/invitations/lookup", json={"token": token})
    assert again.status_code == 404


@requires_database
async def test_existing_user_joins_by_accepting_while_signed_in(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    guest = await register(db_client, email=GUEST, organization_name="Своё бюро")

    token = token_of(await invite(db_client, owner))

    # Без входа приглашение на занятую почту не принимается: иначе ссылка
    # из письма открывала бы чужую учётную запись любому, кто её перехватил.
    anonymous = await db_client.post(
        "/auth/invitations/accept", json={"token": token, "password": PASSWORD}
    )
    assert anonymous.status_code == 403

    accepted = await db_client.post(
        "/auth/invitations/accept", headers=guest.headers, json={"token": token}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["new_account"] is False

    me = await db_client.get("/auth/me", headers=guest.headers)
    organizations = {item["organization_id"] for item in me.json()["memberships"]}

    assert str(owner.organization_id) in organizations
    assert len(organizations) == 2


@requires_database
async def test_invitation_is_for_the_named_mailbox_only(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    token = token_of(await invite(db_client, owner))

    response = await db_client.post(
        "/auth/invitations/accept", headers=stranger.headers, json={"token": token}
    )

    assert response.status_code == 403
    assert GUEST in response.json()["detail"]


@requires_database
async def test_expired_invitation_is_refused(db_client: AsyncClient, session: AsyncSession) -> None:
    owner = await register(db_client)
    token = token_of(await invite(db_client, owner))

    await session.execute(
        update(Invitation).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()

    response = await db_client.post("/auth/invitations/lookup", json={"token": token})

    assert response.status_code == 409
    assert "истёк" in response.json()["detail"]

    # В списке команды оно остаётся — помеченным: его надо видеть, чтобы
    # отозвать или выписать заново.
    team = await db_client.get("/team", headers=owner.headers)
    assert team.json()["invitations"][0]["expired"] is True


@requires_database
async def test_reinviting_replaces_the_previous_link(db_client: AsyncClient) -> None:
    """У человека должна работать последняя ссылка, а не та, что он потерял."""
    owner = await register(db_client)
    first = token_of(await invite(db_client, owner))
    second = token_of(await invite(db_client, owner, role="manager"))

    assert (
        await db_client.post("/auth/invitations/lookup", json={"token": first})
    ).status_code == 404

    preview = await db_client.post("/auth/invitations/lookup", json={"token": second})
    assert preview.status_code == 200
    assert preview.json()["role"] == "manager"


@requires_database
async def test_revoked_invitation_stops_working(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    owner = await register(db_client)
    token = token_of(await invite(db_client, owner))
    invitation_id = await session.scalar(select(Invitation.id))

    revoked = await db_client.delete(f"/team/invitations/{invitation_id}", headers=owner.headers)
    assert revoked.status_code == 204

    response = await db_client.post("/auth/invitations/lookup", json={"token": token})
    assert response.status_code == 404


@requires_database
async def test_member_of_the_team_cannot_be_invited_twice(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    token = token_of(await invite(db_client, owner))
    await accept_as_new(db_client, token)

    response = await db_client.post(
        "/team/invitations", headers=owner.headers, json={"email": GUEST, "role": "viewer"}
    )

    assert response.status_code == 409


@requires_database
async def test_only_owner_grants_and_touches_ownership(db_client: AsyncClient) -> None:
    """Администратор распоряжается людьми, но не самим пространством."""
    owner = await register(db_client)
    admin_headers = await accept_as_new(
        db_client, token_of(await invite(db_client, owner, role="admin"))
    )
    workspace = owner.organization_id

    # Администратор не выписывает владельца.
    response = await db_client.post(
        "/team/invitations",
        headers={**admin_headers, "X-Organization-Id": str(workspace)},
        json={"email": "third@example.com", "role": "owner"},
    )
    assert response.status_code == 403

    # И не трогает роль владельца.
    response = await db_client.patch(
        f"/team/members/{owner.user_id}",
        headers={**admin_headers, "X-Organization-Id": str(workspace)},
        json={"role": "viewer"},
    )
    assert response.status_code == 403

    # Владелец — может: и назначить, и снять.
    me = await db_client.get("/auth/me", headers=admin_headers)
    admin_id = me.json()["user"]["id"]

    promoted = await db_client.patch(
        f"/team/members/{admin_id}", headers=owner.headers, json={"role": "owner"}
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "owner"


@requires_database
async def test_nobody_changes_their_own_role_or_removes_themselves(db_client: AsyncClient) -> None:
    """Единственный владелец, понизивший себя, оставил бы пространство без хозяина."""
    owner = await register(db_client)

    changed = await db_client.patch(
        f"/team/members/{owner.user_id}", headers=owner.headers, json={"role": "viewer"}
    )
    removed = await db_client.delete(f"/team/members/{owner.user_id}", headers=owner.headers)

    assert changed.status_code == 409
    assert removed.status_code == 409


@requires_database
async def test_removed_member_loses_the_workspace_but_keeps_the_account(
    db_client: AsyncClient,
) -> None:
    owner = await register(db_client)
    guest_headers = await accept_as_new(db_client, token_of(await invite(db_client, owner)))

    me = await db_client.get("/auth/me", headers=guest_headers)
    guest_id = me.json()["user"]["id"]

    removed = await db_client.delete(f"/team/members/{guest_id}", headers=owner.headers)
    assert removed.status_code == 204

    # Доступ в пространство закрыт немедленно — участие проверяется на
    # каждом запросе, а не при входе.
    refused = await db_client.get(
        "/team", headers={**guest_headers, "X-Organization-Id": str(owner.organization_id)}
    )
    assert refused.status_code == 403

    # Учётная запись жива.
    still_me = await db_client.get("/auth/me", headers=guest_headers)
    assert still_me.status_code == 200
    assert still_me.json()["memberships"] == []


@requires_database
async def test_translator_sees_the_team_but_cannot_manage_it(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    headers = await accept_as_new(db_client, token_of(await invite(db_client, owner)))
    scoped = {**headers, "X-Organization-Id": str(owner.organization_id)}

    team = await db_client.get("/team", headers=scoped)
    assert team.status_code == 200
    assert team.json()["my_role"] == "translator"
    assert len(team.json()["members"]) == 2

    refused = await db_client.post(
        "/team/invitations", headers=scoped, json={"email": "x@example.com", "role": "viewer"}
    )
    assert refused.status_code == 403
