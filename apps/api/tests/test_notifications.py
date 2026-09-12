"""Уведомления о готовности книги.

Отправка пока заглушена, и главное, что здесь проверяется, — честность:
система нигде не утверждает, что уведомление отправлено, пока его никто не
отправлял, и называет настоящую причину, а не общую.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationSettings
from app.models.organization import Membership, Role
from app.services.notify import NotificationService, clean_username, ready_message
from tests.conftest import requires_database
from tests.factories import register

SETTINGS = {
    "email_enabled": True,
    "email_extra": "bureau@example.com",
    "telegram_enabled": True,
    "telegram_username": "@ivanov",
}


def test_username_is_stored_without_the_at_sign() -> None:
    """Иначе «@ivanov» однажды не совпадёт с «ivanov»."""
    assert clean_username("@ivanov") == "ivanov"
    assert clean_username(" ivanov ") == "ivanov"
    assert clean_username("@") is None
    assert clean_username(None) is None


def test_ready_message_says_what_to_do_next() -> None:
    document_id = uuid.uuid4()

    clean = ready_message(title="Насосы", document_id=document_id, translated=120, flagged=0)
    dirty = ready_message(title="Насосы", document_id=document_id, translated=120, flagged=7)

    assert "Насосы" in clean.subject
    assert "ни к чему не придрались" in clean.body
    assert "Проверки отметили 7" in dirty.body
    # Ссылка ведёт на книгу: уведомление без адреса заставляет искать её
    # руками.
    assert str(document_id) in dirty.body


@requires_database
async def test_untouched_workspace_reports_channels_off(db_client: AsyncClient) -> None:
    """«Ещё не настраивали» и «выключено» для читающего — одно и то же."""
    account = await register(db_client)

    response = await db_client.get("/settings/notifications", headers=account.headers)
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["email_enabled"] is False
    assert body["telegram_enabled"] is False
    assert body["telegram_username"] is None
    assert body["telegram_linked"] is False
    # Отправка ещё не подключена, и витрина обязана об этом сказать.
    assert body["email_ready"] is False
    assert body["telegram_ready"] is False


@requires_database
async def test_settings_are_saved(db_client: AsyncClient) -> None:
    account = await register(db_client)

    saved = await db_client.put("/settings/notifications", headers=account.headers, json=SETTINGS)
    body = saved.json()

    assert saved.status_code == 200, saved.text
    assert body["email_extra"] == "bureau@example.com"
    # Хранится без «собачки», хотя введена с ней.
    assert body["telegram_username"] == "ivanov"
    # Боту человек ещё не писал — значит, отправлять некуда.
    assert body["telegram_linked"] is False

    read = await db_client.get("/settings/notifications", headers=account.headers)

    assert read.json()["telegram_username"] == "ivanov"


@requires_database
async def test_changing_the_nick_drops_the_link(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """🔥 Номер разговора принадлежал прежнему человеку.

    Оставить его при смене ника — значит отправить чужую переписку не тому.
    """
    account = await register(db_client)
    await db_client.put("/settings/notifications", headers=account.headers, json=SETTINGS)

    # Так это выглядит после того, как человек написал боту.
    settings = await session.scalar(
        NotificationSettings.__table__.select().where(
            NotificationSettings.organization_id == account.organization_id
        )
    )
    assert settings is not None

    await session.execute(
        NotificationSettings.__table__.update()
        .where(NotificationSettings.organization_id == account.organization_id)
        .values(telegram_chat_id="12345")
    )
    await session.commit()

    linked = await db_client.get("/settings/notifications", headers=account.headers)
    assert linked.json()["telegram_linked"] is True

    changed = await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={**SETTINGS, "telegram_username": "petrov"},
    )

    assert changed.json()["telegram_username"] == "petrov"
    assert changed.json()["telegram_linked"] is False


@requires_database
async def test_viewer_cannot_change_notifications(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Канал общий: вписанный в него чужой ник получит названия всех книг."""
    owner = await register(db_client)

    guest = await register(db_client, email="guest@example.com", organization_name="Своя контора")
    session.add(
        Membership(organization_id=owner.organization_id, user_id=guest.user_id, role=Role.VIEWER)
    )
    await session.flush()

    headers = guest.headers_for(owner.organization_id)

    assert (
        await db_client.put("/settings/notifications", headers=headers, json=SETTINGS)
    ).status_code == 403
    # Смотреть при этом можно: запрет касается изменения, а не чтения.
    assert (await db_client.get("/settings/notifications", headers=headers)).status_code == 200


@requires_database
async def test_settings_do_not_cross_workspaces(db_client: AsyncClient) -> None:
    account = await register(db_client)
    await db_client.put("/settings/notifications", headers=account.headers, json=SETTINGS)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    response = await db_client.get("/settings/notifications", headers=stranger.headers)

    assert response.json()["telegram_username"] is None
    assert response.json()["email_enabled"] is False


@requires_database
async def test_nothing_claims_to_be_sent(db_client: AsyncClient, session: AsyncSession) -> None:
    """🔥 Отчёт о работе, которой не было, хуже отсутствия отчёта."""
    account = await register(db_client)
    await db_client.put("/settings/notifications", headers=account.headers, json=SETTINGS)

    message = ready_message(
        title="Насосы", document_id=account.organization_id, translated=10, flagged=0
    )
    deliveries = await NotificationService(session).notify(account.organization_id, message)

    assert len(deliveries) == 2
    assert all(not delivery.sent for delivery in deliveries)


@requires_database
async def test_telegram_names_the_real_reason(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """«Не отправлено» бывает разным, и чинится это разными руками."""
    account = await register(db_client)
    message = ready_message(
        title="Насосы", document_id=account.organization_id, translated=10, flagged=0
    )

    # Канал включён, ник не дописан — чинит человек, и прямо сейчас.
    await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"telegram_enabled": True, "telegram_username": ""},
    )
    empty = await NotificationService(session).notify(account.organization_id, message)

    assert "ник не указан" in empty[0].detail

    # Ник есть, но боту человек не писал — чинит тоже он, но в Телеграме.
    await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"telegram_enabled": True, "telegram_username": "ivanov"},
    )
    unlinked = await NotificationService(session).notify(account.organization_id, message)

    assert "напишите боту" in unlinked[0].detail
    assert unlinked[0].to == "@ivanov"


@requires_database
async def test_silence_when_nobody_asked(db_client: AsyncClient, session: AsyncSession) -> None:
    """Пустой список означает «сообщать некуда» — и ничего больше."""
    account = await register(db_client)

    message = ready_message(
        title="Насосы", document_id=account.organization_id, translated=10, flagged=0
    )

    assert await NotificationService(session).notify(account.organization_id, message) == []


@requires_database
async def test_email_falls_back_to_the_one_who_asked(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Пустой адрес — писать тому, кто книгу и поставил: он её ждёт."""
    account = await register(db_client)
    await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"email_enabled": True, "telegram_enabled": False},
    )

    message = ready_message(
        title="Насосы", document_id=account.organization_id, translated=10, flagged=0
    )
    deliveries = await NotificationService(session).notify(
        account.organization_id, message, requested_by_email="owner@example.com"
    )

    assert len(deliveries) == 1
    assert deliveries[0].to == "owner@example.com"


@requires_database
async def test_letter_goes_to_the_one_who_asked_and_to_the_shared_box(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Заказчик перевода — первым, общий ящик — вторым."""
    account = await register(db_client)
    await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"email_enabled": True, "email_extra": "bureau@example.com"},
    )

    message = ready_message(
        title="Насосы", document_id=account.organization_id, translated=10, flagged=0
    )
    deliveries = await NotificationService(session).notify(
        account.organization_id, message, requested_by_email="owner@example.com"
    )

    assert [delivery.to for delivery in deliveries] == [
        "owner@example.com",
        "bureau@example.com",
    ]


@requires_database
async def test_the_same_address_is_not_written_twice(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Письмо, пришедшее дважды, выглядит как сбой, а не как забота."""
    account = await register(db_client)
    await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"email_enabled": True, "email_extra": "Owner@Example.com"},
    )

    message = ready_message(
        title="Насосы", document_id=account.organization_id, translated=10, flagged=0
    )
    deliveries = await NotificationService(session).notify(
        account.organization_id, message, requested_by_email="owner@example.com"
    )

    assert [delivery.to for delivery in deliveries] == ["owner@example.com"]


@requires_database
async def test_russian_layout_is_caught(db_client: AsyncClient) -> None:
    """🔥 Забытая раскладка: «ivanov» набирается как «швфтщм».

    Строка выглядит правдоподобно, форма её принимает, письмо уходит в
    никуда — и человек месяц ждёт уведомлений, которых не будет.
    """
    account = await register(db_client)

    address = await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"email_enabled": True, "email_extra": "швфтщм@учфьздуюсщь"},
    )

    assert address.status_code == 422
    assert "русскими буквами" in address.text

    nick = await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"telegram_enabled": True, "telegram_username": "@швфтщм"},
    )

    assert nick.status_code == 422
    assert "русскими буквами" in nick.text


@requires_database
async def test_broken_address_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"email_enabled": True, "email_extra": "не-адрес"},
    )

    assert response.status_code == 422


@requires_database
async def test_short_nick_is_refused(db_client: AsyncClient) -> None:
    """Ник в Телеграме — от пяти знаков: короче их не бывает."""
    account = await register(db_client)

    response = await db_client.put(
        "/settings/notifications",
        headers=account.headers,
        json={"telegram_enabled": True, "telegram_username": "@iv"},
    )

    assert response.status_code == 422
    assert "от 5 знаков" in response.text
