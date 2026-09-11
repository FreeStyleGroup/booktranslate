"""Пересчёт расхода в деньги.

Число, по которому назначают цену заказчику, обязано быть проверяемым: тут
проверяется, что кэш считается по своей ставке, а неизвестная модель не
выдаётся за бесплатную.
"""

from app.services.pricing import PRICES, WEB_SEARCH_USD_PER_1000, estimate_usd, forecast
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


def test_web_searches_are_paid_apart_from_tokens() -> None:
    """В счётчиках токенов поиска не видно вовсе — а платить за него надо."""
    without = estimate_usd("claude-opus-5", input_tokens=1000, output_tokens=1000)
    with_searches = estimate_usd(
        "claude-opus-5", input_tokens=1000, output_tokens=1000, searches=10
    )

    assert without is not None and with_searches is not None
    assert round(with_searches - without, 4) == round(10 * WEB_SEARCH_USD_PER_1000 / 1000, 4)


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


def test_forecast_grows_with_the_text() -> None:
    """Смета должна расти вместе с книгой — иначе это не смета."""
    small = forecast("claude-opus-5", characters=10_000, context_segments=2)
    big = forecast("claude-opus-5", characters=100_000, context_segments=2)

    assert small.usd is not None and big.usd is not None
    assert big.usd > small.usd


def test_forecast_counts_the_context_sent_with_each_segment() -> None:
    """Соседние сегменты уходят в запрос и оплачиваются вместе с ним.

    Смета без них занижала бы счёт в несколько раз — ровно на то, что
    приложено к каждому сегменту ради связности перевода.
    """
    bare = forecast("claude-opus-5", characters=10_000, context_segments=0)
    with_context = forecast("claude-opus-5", characters=10_000, context_segments=2)

    assert with_context.input_tokens > bare.input_tokens
    # Перевод от контекста не толстеет: соседи переводить не нужно.
    assert with_context.output_tokens == bare.output_tokens


def test_forecast_of_unknown_model_names_tokens_but_not_money() -> None:
    """Токены посчитать можно всегда, деньги — только по прейскуранту."""
    estimate = forecast("stub", characters=10_000, context_segments=2)

    assert estimate.input_tokens > 0
    assert estimate.usd is None
