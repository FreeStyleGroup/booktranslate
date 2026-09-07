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

from app.core.config import get_settings
from app.services.providers.base import (
    EMPTY_CONTEXT,
    Neighbourhood,
    ProviderError,
    StubProvider,
    TranslationProvider,
    TranslationRequest,
)
from app.services.providers.claude import ClaudeProvider, ClaudeSettings

STUB = "stub"
CLAUDE = "claude"


@lru_cache
def get_provider() -> TranslationProvider:
    """Провайдер перевода приложения.

    Функция, а не глобальный объект: так её подменяют в тестах через
    зависимости FastAPI, не трогая настройки процесса.
    """
    settings = get_settings()

    if settings.translation_provider != CLAUDE:
        return StubProvider()

    # Импорт внутри функции намеренно: пакет модели весит немало и тянет
    # свой HTTP-клиент, а при работе с заглушкой он не нужен вовсе.
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        # Ключ читается из окружения самим клиентом, если не задан явно:
        # ANTHROPIC_API_KEY, либо профиль, настроенный на машине.
        api_key=settings.anthropic_api_key or None,
        # Перевод книги — сотни запросов подряд; сетевой сбой на середине не
        # должен ронять весь документ.
        max_retries=settings.anthropic_max_retries,
        timeout=settings.anthropic_timeout_seconds,
    )

    return ClaudeProvider(
        client,
        ClaudeSettings(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            effort=settings.anthropic_effort or None,
            use_fallbacks=settings.anthropic_use_fallbacks,
        ),
    )


__all__ = [
    "CLAUDE",
    "EMPTY_CONTEXT",
    "STUB",
    "ClaudeProvider",
    "ClaudeSettings",
    "Neighbourhood",
    "ProviderError",
    "StubProvider",
    "TranslationProvider",
    "TranslationRequest",
    "get_provider",
]
