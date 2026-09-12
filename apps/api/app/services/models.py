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
        "claude-opus-5",
        "Claude Opus 5",
        "Самая точная: сложный текст, редкая терминология, длинные абзацы с отсылками.",
        PRICES.get("claude-opus-5"),
    ),
    ModelChoice(
        "claude-sonnet-5",
        "Claude Sonnet 5",
        "Середина: заметно дешевле и быстрее, качества хватает на типовую документацию.",
        PRICES.get("claude-sonnet-5"),
    ),
    ModelChoice(
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        "Самая быстрая и дешёвая: черновики и большой объём однотипного текста.",
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
