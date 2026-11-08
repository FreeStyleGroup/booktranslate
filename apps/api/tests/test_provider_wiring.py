"""Как собирается клиент модели: напрямую и через шлюз.

Проверка выглядит мелкой, но ловит ровно ту ошибку, которая на боевом
сервере неотличима от неверного ключа: шлюз ждёт ключ в «Authorization:
Bearer», а клиент по умолчанию кладёт его в «x-api-key», и в ответ прилетает
отказ в доступе. Искать это в переписке с поддержкой шлюза дороже, чем
закрепить тестом.

Сеть здесь не нужна: клиент собирается, но никуда не ходит.
"""

from collections.abc import Iterator

import pytest

from app import cli
from app.core.config import get_settings
from app.services import providers
from app.services.providers import ProviderError, Usage


@pytest.fixture(autouse=True)
def fresh_caches() -> Iterator[None]:
    """Клиент и провайдер кешируются на процесс — иначе тесты видят чужой."""
    providers._client.cache_clear()
    providers.get_provider.cache_clear()

    yield

    providers._client.cache_clear()
    providers.get_provider.cache_clear()


def test_direct_call_puts_the_key_in_x_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_base_url", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-example")

    client = providers._client()

    assert str(client.base_url).startswith("https://api.anthropic.com")
    assert client.auth_headers == {"X-Api-Key": "sk-ant-example"}


def test_gateway_gets_the_key_as_a_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_base_url", "https://api.aitunnel.ru")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-aitunnel-example")

    client = providers._client()

    assert str(client.base_url).startswith("https://api.aitunnel.ru")
    assert client.auth_headers == {"Authorization": "Bearer sk-aitunnel-example"}


def test_gateway_turns_off_server_side_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запасная модель — возможность Anthropic, и шлюз её не проксирует.

    Оставленная включённой, она отвергает не отдельную пачку, а каждый
    запрос: бета-заголовок шлюзу незнаком.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "translation_provider", providers.CLAUDE)
    monkeypatch.setattr(settings, "anthropic_use_fallbacks", True)
    monkeypatch.setattr(settings, "anthropic_base_url", "https://api.aitunnel.ru")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-aitunnel-example")

    provider = providers.get_provider()

    assert isinstance(provider, providers.ClaudeProvider)
    assert provider._settings.use_fallbacks is False


def test_direct_call_keeps_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "translation_provider", providers.CLAUDE)
    monkeypatch.setattr(settings, "anthropic_use_fallbacks", True)
    monkeypatch.setattr(settings, "anthropic_base_url", "")

    provider = providers.get_provider()

    assert isinstance(provider, providers.ClaudeProvider)
    assert provider._settings.use_fallbacks is True


def test_models_with_a_lower_default_get_the_same_depth_as_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_effort", "")

    assert providers._settings_for("claude-opus-5-5").effort == "high"
    assert providers._settings_for("claude-haiku-5-5").effort == "high"
    assert providers._settings_for("claude-opus-5").effort is None


def test_platform_setting_wins_but_not_where_the_model_refuses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_effort", "max")

    assert providers._settings_for("claude-opus-5-5").effort == "max"
    assert providers._settings_for("claude-haiku-4-5").effort is None


def test_fallback_only_goes_directly_and_only_where_it_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_use_fallbacks", True)
    monkeypatch.setattr(settings, "anthropic_base_url", "")

    assert providers._settings_for("claude-opus-5-5").use_fallbacks is True
    assert providers._settings_for("claude-haiku-5-5").use_fallbacks is False
    assert providers._settings_for("claude-opus-5-5", fallbacks=False).use_fallbacks is False

    monkeypatch.setattr(settings, "anthropic_base_url", "https://api.aitunnel.ru")
    assert providers._settings_for("claude-opus-5-5").use_fallbacks is False


async def test_check_of_all_models_reports_each_and_does_not_stop_at_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "translation_provider", "claude")

    async def works(model: str) -> tuple[str, Usage]:
        return "готово", Usage(input_tokens=1000, output_tokens=100)

    async def refuses(model: str) -> tuple[str, Usage]:
        if model == "claude-sonnet-5":
            raise ProviderError("шлюз не знает эту модель")

        return "готово", Usage()

    monkeypatch.setattr(cli, "_probe_translation", works)
    monkeypatch.setattr(cli, "_probe_review", works)
    monkeypatch.setattr(cli, "_probe_resolve", works)
    monkeypatch.setattr(cli, "_probe_figure", refuses)

    assert await cli.check_all_models() is False

    printed = capsys.readouterr().out
    assert "claude-fable-5-1" in printed
    assert "claude-haiku-4-5" in printed
    assert "рисунок: ОТКАЗ" in printed
    assert "шлюз не знает эту модель" in printed


def test_probe_picture_is_a_real_image() -> None:
    assert cli._probe_picture().startswith(b"\x89PNG")
