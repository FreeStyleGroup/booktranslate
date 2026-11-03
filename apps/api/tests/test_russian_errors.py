"""Отказы API доходят до человека дословно, поэтому они на русском."""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import register


def russian(text: str) -> bool:
    return any("а" <= letter.lower() <= "я" for letter in text)


@requires_database
async def test_missing_field_is_told_in_russian(db_client: AsyncClient) -> None:
    response = await db_client.post("/auth/login", json={"email": "a@example.com"})

    assert response.status_code == 422
    assert russian(response.json()["detail"][0]["msg"])


@requires_database
async def test_too_long_value_names_the_limit(db_client: AsyncClient) -> None:
    account = await register(db_client)
    response = await db_client.post(
        "/projects",
        headers=account.headers,
        json={"name": "x" * 100_000, "source_language": "en", "target_language": "ru"},
    )

    assert response.status_code == 422
    message = response.json()["detail"][0]["msg"]
    assert russian(message)
    assert any(letter.isdigit() for letter in message)


@requires_database
async def test_bad_identifier_and_value_are_told_in_russian(db_client: AsyncClient) -> None:
    account = await register(db_client)

    for response in (
        await db_client.get("/books/not-a-uuid", headers=account.headers),
        await db_client.get("/issues?state=nonsense", headers=account.headers),
    ):
        assert response.status_code == 422
        assert russian(response.json()["detail"][0]["msg"])


@requires_database
async def test_validation_does_not_echo_the_input(db_client: AsyncClient) -> None:
    secret = "correct-horse-battery-" + "x" * 5000
    response = await db_client.post("/auth/login", json={"email": "nope", "password": secret})

    assert response.status_code == 422
    assert secret not in response.text


@requires_database
async def test_unknown_route_and_method_are_told_in_russian(db_client: AsyncClient) -> None:
    missing = await db_client.get("/no-such-route")
    assert missing.status_code == 404
    assert russian(missing.json()["detail"])

    wrong = await db_client.delete("/auth/login")
    assert wrong.status_code == 405
    assert russian(wrong.json()["detail"])
