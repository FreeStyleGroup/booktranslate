"""Защищённое содержимое: заменители, их сверка и сборка блока из частей."""

import pytest
from bs4 import BeautifulSoup, Tag

from app.models.block import BlockKind
from app.services.parsers.markup import block_text, protected_spans
from app.services.protection import (
    Span,
    TokenMismatchError,
    find_spans,
    join_pieces,
    mask,
    stored_spans,
    unmask,
)
from app.services.translation_runner import is_protected


def masked_of(text: str, known: list[Span] | None = None):
    return mask(text, find_spans(text, known or []))


def test_placeholder_url_and_code_are_hidden_from_the_model() -> None:
    masked = masked_of("Set {name} with `make all`, see https://example.com/a?b=1 now.")

    assert masked.text == "Set ⟦1⟧ with ⟦2⟧, see ⟦3⟧ now."
    assert masked.originals == ("{name}", "`make all`", "https://example.com/a?b=1")


def test_content_returns_verbatim_and_may_move() -> None:
    masked = masked_of("Set {name} with `make all`.")

    assert unmask("С помощью ⟦2⟧ задайте ⟦1⟧.", masked) == "С помощью `make all` задайте {name}."


@pytest.mark.parametrize(
    ("answer", "lost", "extra"),
    [
        ("Задайте значение.", ["⟦1⟧"], []),
        ("Задайте ⟦1⟧ и ⟦1⟧.", [], ["⟦1⟧"]),
        ("Задайте ⟦1⟧ и ⟦2⟧.", [], ["⟦2⟧"]),
    ],
)
def test_broken_tokens_are_refused(answer: str, lost: list[str], extra: list[str]) -> None:
    with pytest.raises(TokenMismatchError) as caught:
        unmask(answer, masked_of("Set {name}."))

    assert caught.value.lost == lost
    assert caught.value.extra == extra


def test_text_with_the_brackets_themselves_is_left_alone() -> None:
    masked = masked_of("The notation ⟦1⟧ means {x}.")

    assert masked.originals == ()
    assert unmask("Запись ⟦1⟧ означает {x}.", masked) == "Запись ⟦1⟧ означает {x}."


def test_marked_span_wins_over_what_is_inside_it() -> None:
    """`<code>{x}</code>` — один кусок кода, а не код с подстановкой внутри."""
    masked = masked_of("Use f({x}) here.", [Span(4, 10, "code")])

    assert masked.originals == ("f({x})",)


def test_stored_spans_are_cut_to_the_piece() -> None:
    location = {"protected": [{"start": 8, "end": 14, "kind": "formula"}]}

    assert stored_spans(location, offset=0, length=10) == [Span(8, 10, "formula")]
    assert stored_spans(location, offset=10, length=10) == [Span(0, 4, "formula")]
    assert stored_spans(location, offset=20, length=10) == []


def test_pieces_keep_the_separators_of_the_source() -> None:
    assert (
        join_pieces(["First one. ", "Second one.\n"], [" Первое. ", "Второе."])
        == "Первое. Второе.\n"
    )


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        (BlockKind.CODE, "open(valve)", True),
        (BlockKind.TABLE_CELL, "12,5", True),
        (BlockKind.PARAGRAPH, "— 3.2 —", True),
        (BlockKind.TABLE_CELL, "12 bar", False),
        (BlockKind.PARAGRAPH, "Клапан", False),
    ],
)
def test_what_never_goes_to_the_model(kind: BlockKind, text: str, expected: bool) -> None:
    assert is_protected(kind, text) is expected


def element_of(markup: str) -> Tag:
    element = BeautifulSoup(markup, "html.parser").find(True)
    assert isinstance(element, Tag)

    return element


def test_parser_marks_inline_formula_and_code() -> None:
    element = element_of(
        "<p>Where <math><mi>r</mi><mn>2</mn></math>  is set by <code>radius( )</code>.</p>"
    )
    text = block_text(element)

    assert text == "Where r2 is set by radius( )."
    assert protected_spans(element, text) == [
        {"start": 6, "end": 8, "kind": "formula"},
        {"start": 19, "end": 28, "kind": "code"},
    ]


def test_parser_does_not_mark_a_listing() -> None:
    element = element_of("<pre><code>open(valve)</code></pre>")

    assert protected_spans(element, block_text(element)) == []
