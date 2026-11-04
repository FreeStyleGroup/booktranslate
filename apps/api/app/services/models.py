"""Каталог моделей перевода, из которого выбирает рабочее пространство.

Каталог в коде, а не в базе: у каждой записи прейскурант и слова о том,
для чего она годится, и то и другое меняется вместе с выкатом, а не
рукой администратора. Пространство хранит только имя выбранной.

Умолчание площадки (`ANTHROPIC_MODEL`) всегда в списке, даже если его нет в
каталоге: через шлюз имя модели бывает своим, и пространство, ничего не
выбиравшее, обязано видеть, чем его переводят.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.services.pricing import PRICES, Price


@dataclass(frozen=True, slots=True)
class ModelChoice:
    id: str
    title: str
    # Для чего годится — словами, по которым выбирают. Цена отдельно: она
    # берётся из прейскуранта и в тексте не повторяется.
    note: str
    price: Price | None


CATALOG: tuple[ModelChoice, ...] = (
    ModelChoice(
        "claude-fable-5-1",
        "Claude Fable 5.1",
        "Самая сильная и самая дорогая: трудный текст, где важна каждая формулировка. "
        "Отвечает дольше остальных.",
        PRICES.get("claude-fable-5-1"),
    ),
    ModelChoice(
        "claude-opus-5-5",
        "Claude Opus 5.5",
        "Новейшая точная модель, дешевле Opus 5: сложный текст, редкая терминология, "
        "длинные абзацы с отсылками.",
        PRICES.get("claude-opus-5-5"),
    ),
    ModelChoice(
        "claude-opus-5",
        "Claude Opus 5",
        "Прежнее поколение точной модели: для сравнения с Opus 5.5 на той же книге.",
        PRICES.get("claude-opus-5"),
    ),
    ModelChoice(
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5",
        "Новейшая средняя модель: заметно дешевле и быстрее точных, качества хватает "
        "на типовую документацию.",
        PRICES.get("claude-sonnet-5-5"),
    ),
    ModelChoice(
        "claude-sonnet-5",
        "Claude Sonnet 5",
        "Прежнее поколение средней модели: цена та же, что у Sonnet 5.5.",
        PRICES.get("claude-sonnet-5"),
    ),
    ModelChoice(
        "claude-haiku-5-5",
        "Claude Haiku 5.5",
        "Самая быстрая и дешёвая: черновики и большой объём однотипного текста.",
        PRICES.get("claude-haiku-5-5"),
    ),
    ModelChoice(
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        "Прежнее поколение: дороже Haiku 5.5, оставлена для сравнения.",
        PRICES.get("claude-haiku-4-5"),
    ),
)


def default_model() -> str:
    """Чем переводит пространство, которое ничего не выбирало."""
    return get_settings().anthropic_model


def available_models() -> list[ModelChoice]:
    """Каталог с гарантированным умолчанием площадки — первым."""
    default = default_model()
    known = [choice for choice in CATALOG if choice.id == default]

    if known:
        return [*known, *(choice for choice in CATALOG if choice.id != default)]

    return [
        ModelChoice(default, default, "Модель площадки по умолчанию.", PRICES.get(default)),
        *CATALOG,
    ]


def is_available(model: str) -> bool:
    return any(choice.id == model for choice in available_models())


# Глубина по умолчанию у этих моделей ниже, чем у соседних. Без явного значения они проигрывали бы
# в сравнении на той же книге из-за настройки, а не из-за качества.
_HIGH_EFFORT_BY_DEFAULT = frozenset({"claude-opus-5-5", "claude-haiku-5-5"})

# Эта модель не принимает глубину: запрос с ней отвергается целиком.
_WITHOUT_EFFORT = frozenset({"claude-haiku-4-5"})

# Запасная модель при отказе есть не у всех: у остальных такой запрос просто не пройдёт.
_WITH_SERVER_FALLBACK = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)


def effort_for(model: str, configured: str) -> str | None:
    """Глубина для запроса: настройка площадки, а без неё умолчание модели."""
    if model in _WITHOUT_EFFORT:
        return None

    if configured:
        return configured

    return "high" if model in _HIGH_EFFORT_BY_DEFAULT else None


def has_server_fallback(model: str) -> bool:
    return model in _WITH_SERVER_FALLBACK
