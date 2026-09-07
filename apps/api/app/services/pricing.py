"""Пересчёт расхода в деньги.

Токены хранятся, деньги считаются. Разница принципиальная: цены меняются, а
потраченное на эту книгу — исторический факт, и пересчитывать его задним
числом по новому прейскуранту значит подделывать отчёт. Поэтому в базе
лежат токены, а стоимость собирается на лету и всегда помечена как оценка.

Оценка, а не счёт, ещё и потому, что сторона поставщика считает по-своему:
пробные периоды, скидки за объём, разные ставки у облачных площадок. Число
здесь годится, чтобы понять порядок и назначить цену заказчику, а не чтобы
сверять с выставленным счётом.
"""

from dataclasses import dataclass

# Цены в долларах за миллион токенов. Сверено 07.09.2026; при смене модели
# или тарифа таблицу надо обновить — молча устаревшая цена хуже её
# отсутствия, потому что выглядит как знание.
PRICES: dict[str, "Price"] = {}

# Множитель для чтения из кэша: примерно десятая часть обычного ввода. Ради
# него кэш и заводился, и в отчёте это должно быть видно.
CACHE_READ_RATIO = 0.1

# Запись в кэш дороже обычного ввода, но платится один раз.
CACHE_WRITE_RATIO = 1.25


@dataclass(frozen=True, slots=True)
class Price:
    """Ставки одной модели, долларов за миллион токенов."""

    input_usd: float
    output_usd: float


PRICES.update(
    {
        "claude-opus-5": Price(input_usd=5.00, output_usd=25.00),
        "claude-sonnet-5": Price(input_usd=2.00, output_usd=10.00),
        "claude-haiku-4-5": Price(input_usd=1.00, output_usd=5.00),
    }
)

MILLION = 1_000_000


def estimate_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Оценка стоимости перевода.

    `None` означает «модель не в прейскуранте» — и это честнее нуля:
    заглушка ничего не стоит, а неизвестная модель стоит неизвестно
    сколько, и показывать её как бесплатную нельзя.
    """
    price = PRICES.get(model)

    if price is None:
        return None

    total = (
        input_tokens * price.input_usd
        + cached_input_tokens * price.input_usd * CACHE_READ_RATIO
        + cache_write_tokens * price.input_usd * CACHE_WRITE_RATIO
        + output_tokens * price.output_usd
    )

    return round(total / MILLION, 4)
