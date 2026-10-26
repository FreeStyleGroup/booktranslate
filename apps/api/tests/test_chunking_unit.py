"""Нарезка блока для модели: склейка частей — ровно текст блока."""

import random

from app.models.block import BlockKind
from app.services.chunking import chunk, estimate_tokens


def test_short_block_is_one_chunk() -> None:
    assert chunk(
        "Короткий абзац.", BlockKind.PARAGRAPH, target_chars=100, hard_limit_chars=200
    ) == ["Короткий абзац."]


def test_long_block_is_cut_at_sentence_ends_without_losing_spaces() -> None:
    text = "First sentence.  Second one!\nThird «quoted.» Fourth?   Fifth."
    parts = chunk(text, BlockKind.PARAGRAPH, target_chars=20, hard_limit_chars=40)

    assert "".join(parts) == text
    assert len(parts) > 1
    # Пробелы после конца предложения — в хвосте части, не в начале следующей.
    assert all(not part[0].isspace() for part in parts)


def test_overlong_sentence_is_cut_between_words() -> None:
    text = "word " * 50 + "end."
    parts = chunk(text, BlockKind.PARAGRAPH, target_chars=30, hard_limit_chars=40)

    assert "".join(parts) == text
    assert all(len(part) <= 40 for part in parts)


def test_word_longer_than_limit_is_never_split() -> None:
    giant = "x" * 120
    text = f"Before. {giant} after."
    parts = chunk(text, BlockKind.PARAGRAPH, target_chars=20, hard_limit_chars=50)

    assert "".join(parts) == text
    assert any(giant in part for part in parts)


def test_code_is_never_cut() -> None:
    listing = "def f():\n    return 1\n" * 200
    assert chunk(listing, BlockKind.CODE, target_chars=10, hard_limit_chars=20) == [listing]


def test_join_equals_text_on_varied_input() -> None:
    """Главное свойство — на сотне случайных текстов с неудобными пробелами."""
    rng = random.Random(20261026)
    alphabet = ["Lorem", "ipsum.", "dolor!", "sit?", "amet…", "«x.»", "\t", "\n", "  ", " "]

    for _ in range(100):
        text = "".join(rng.choice(alphabet) + rng.choice([" ", "  ", "\n", ""]) for _ in range(80))
        parts = chunk(text, BlockKind.PARAGRAPH, target_chars=40, hard_limit_chars=90)

        assert "".join(parts) == text


def test_token_estimate_rounds_up() -> None:
    assert estimate_tokens("abcd", 3.0) == 2
    assert estimate_tokens("", 3.0) == 1
