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

from app.core.config import get_settings
from app.services import providers


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
