"""Пересчёт расхода в деньги.

Число, по которому назначают цену заказчику, обязано быть проверяемым: тут
проверяется, что кэш считается по своей ставке, а неизвестная модель не
выдаётся за бесплатную.
"""

from app.services.pricing import PRICES, estimate_usd
from app.services.providers import Usage


def test_plain_tokens_are_counted_by_the_price_list() -> None:
    price = PRICES["claude-opus-5"]

    result = estimate_usd("claude-opus-5", input_tokens=1_000_000, output_tokens=0)

    assert result == round(price.input_usd, 4)


def test_output_is_dearer_than_input() -> None:
    cheap = estimate_usd("claude-opus-5", input_tokens=100_000, output_tokens=0)
    dear = estimate_usd("claude-opus-5", input_tokens=0, output_tokens=100_000)

    assert cheap is not None and dear is not None
    assert dear > cheap


def test_cache_reads_cost_a_fraction_of_input() -> None:
    """Ради этого кэш и заводился — в отчёте это должно быть видно."""
    plain = estimate_usd("claude-opus-5", input_tokens=1_000_000, output_tokens=0)
    cached = estimate_usd(
        "claude-opus-5", input_tokens=0, output_tokens=0, cached_input_tokens=1_000_000
    )

    assert plain is not None and cached is not None
    assert cached == round(plain * 0.1, 4)


def test_cache_writes_cost_more_than_plain_input() -> None:
    plain = estimate_usd("claude-opus-5", input_tokens=1_000_000, output_tokens=0)
    written = estimate_usd(
        "claude-opus-5", input_tokens=0, output_tokens=0, cache_write_tokens=1_000_000
    )

    assert plain is not None and written is not None
    assert written > plain


def test_unknown_model_is_not_free() -> None:
    """Заглушка ничего не стоит, а неизвестная модель — неизвестно сколько."""
    assert estimate_usd("stub", input_tokens=1_000_000, output_tokens=1_000_000) is None


def test_usage_adds_up() -> None:
    """Расход складывается по пачкам: за книгу платят по всем вызовам сразу."""
    total = Usage(input_tokens=10, output_tokens=5) + Usage(
        input_tokens=1, output_tokens=2, cached_input_tokens=3, cache_write_tokens=4
    )

    assert total == Usage(
        input_tokens=11, output_tokens=7, cached_input_tokens=3, cache_write_tokens=4
    )
