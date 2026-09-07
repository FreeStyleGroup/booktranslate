"""Провайдеры перевода и выбор действующего.

Выбор делается настройкой, а не кодом: на разработке и в CI работает
заглушка (быстро, бесплатно, без сети), в рабочей среде — модель. Без этого
разделения тесты либо ходили бы в сеть, либо проверяли бы не то, что
работает у заказчика.

Клиент модели создаётся один на процесс: у него внутри пул соединений, и
собирать его на каждый запрос значит платить рукопожатием TLS за каждую
пачку сегментов.
"""

from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.services.providers.base import (
    EMPTY_CONTEXT,
    Neighbourhood,
    ProviderError,
    StubProvider,
    Translated,
    TranslationProvider,
    TranslationRequest,
    Usage,
)
from app.services.providers.claude import ClaudeProvider, ClaudeSettings
from app.services.providers.lookup import (
    ClaudeLookup,
    Explanation,
    LookupRequest,
    LookupSettings,
    OfflineLookup,
    Reference,
    TermLookupProvider,
)

STUB = "stub"
CLAUDE = "claude"
OFFLINE = "offline"


@lru_cache
def _client() -> Any:
    """Клиент модели — один на процесс.

    У него внутри пул соединений, и собирать его на каждый запрос значит
    платить рукопожатием TLS за каждую пачку сегментов. Перевод и поиск
    справок пользуются одним и тем же.
    """
    settings = get_settings()

    # Импорт внутри функции намеренно: пакет модели весит немало и тянет
    # свой HTTP-клиент, а при работе с заглушкой он не нужен вовсе.
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(
        # Ключ читается из окружения самим клиентом, если не задан явно:
        # ANTHROPIC_API_KEY, либо профиль, настроенный на машине.
        api_key=settings.anthropic_api_key or None,
        # Перевод книги — сотни запросов подряд; сетевой сбой на середине не
        # должен ронять весь документ.
        max_retries=settings.anthropic_max_retries,
        timeout=settings.anthropic_timeout_seconds,
    )


@lru_cache
def get_provider() -> TranslationProvider:
    """Провайдер перевода приложения.

    Функция, а не глобальный объект: так её подменяют в тестах через
    зависимости FastAPI, не трогая настройки процесса.
    """
    settings = get_settings()

    if settings.translation_provider != CLAUDE:
        return StubProvider()

    return ClaudeProvider(
        _client(),
        ClaudeSettings(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            effort=settings.anthropic_effort or None,
            use_fallbacks=settings.anthropic_use_fallbacks,
        ),
    )


@lru_cache
def get_lookup() -> TermLookupProvider:
    """Источник справок о терминах.

    Выключен по умолчанию, и это не осторожность ради осторожности: поиск
    ходит в сеть, оплачивается отдельно от перевода и у заказчика с закрытым
    контуром может быть запрещён вовсе. Включается осознанно.
    """
    settings = get_settings()

    if settings.term_lookup_provider != CLAUDE:
        return OfflineLookup()

    return ClaudeLookup(
        _client(),
        LookupSettings(
            # Та же модель, что и на переводе: справка по термину решает
            # судьбу сорока сегментов, и экономить на ней — экономить на
            # переводе.
            model=settings.anthropic_model,
            max_tokens=settings.term_lookup_max_tokens,
        ),
    )


__all__ = [
    "CLAUDE",
    "EMPTY_CONTEXT",
    "OFFLINE",
    "STUB",
    "ClaudeLookup",
    "ClaudeProvider",
    "ClaudeSettings",
    "Explanation",
    "LookupRequest",
    "LookupSettings",
    "Neighbourhood",
    "OfflineLookup",
    "ProviderError",
    "Reference",
    "StubProvider",
    "TermLookupProvider",
    "Translated",
    "TranslationProvider",
    "TranslationRequest",
    "Usage",
    "get_lookup",
    "get_provider",
]
