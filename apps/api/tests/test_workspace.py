"""Выбор модели перевода рабочим пространством."""

from httpx import AsyncClient

from app.core.config import get_settings
from app.services import providers
from app.services.models import available_models
from tests.conftest import requires_database
from tests.factories import register


def test_platform_default_is_always_in_the_catalogue_and_first() -> None:
    """Через шлюз имя модели бывает своим — пространство обязано видеть, чем его переводят."""
    settings = get_settings()
    original = settings.anthropic_model

    try:
        settings.anthropic_model = "gateway-special-model"
        choices = available_models()

        assert choices[0].id == "gateway-special-model"
        assert choices[0].price is None
        assert [choice.id for choice in choices[1:]] == [
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-haiku-4-5",
        ]

        settings.anthropic_model = "claude-sonnet-5"
        assert [choice.id for choice in available_models()][0] == "claude-sonnet-5"
    finally:
        settings.anthropic_model = original


def test_provider_name_follows_the_chosen_model() -> None:
    settings = get_settings()
    original = settings.translation_provider

    try:
        settings.translation_provider = providers.CLAUDE
        assert providers.provider_name("claude-haiku-4-5") == "claude-haiku-4-5"
        assert providers.provider_name() == settings.anthropic_model

        settings.translation_provider = providers.STUB
        # С заглушкой имя модели не значит ничего: переводит она.
        assert providers.provider_name("claude-haiku-4-5") == providers.STUB
    finally:
        settings.translation_provider = original


@requires_database
async def test_workspace_reports_the_default_until_it_chooses(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.get("/settings/workspace", headers=account.headers)
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["chosen_model"] is None
    assert body["translation_model"] == body["default_model"]
    assert [item["id"] for item in body["models"]][0] == body["default_model"]
    # Цены приходят вместе с каталогом — витрина не держит своего прейскуранта.
    assert body["models"][0]["input_usd"] is not None


@requires_database
async def test_choice_is_kept_and_can_be_reset(db_client: AsyncClient) -> None:
    account = await register(db_client)

    chosen = await db_client.put(
        "/settings/workspace",
        headers=account.headers,
        json={"translation_model": "claude-haiku-4-5"},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["translation_model"] == "claude-haiku-4-5"

    read = await db_client.get("/settings/workspace", headers=account.headers)
    assert read.json()["chosen_model"] == "claude-haiku-4-5"

    reset = await db_client.put(
        "/settings/workspace", headers=account.headers, json={"translation_model": None}
    )
    assert reset.json()["chosen_model"] is None
    assert reset.json()["translation_model"] == reset.json()["default_model"]


@requires_database
async def test_model_outside_the_catalogue_is_refused(db_client: AsyncClient) -> None:
    """Опечатка ушла бы в запрос и вернулась бы отказом посреди книги."""
    account = await register(db_client)

    response = await db_client.put(
        "/settings/workspace", headers=account.headers, json={"translation_model": "claude-opus-9"}
    )

    assert response.status_code == 400
    assert "нет в каталоге" in response.json()["detail"]
