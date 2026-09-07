"""Нарезка блоков на сегменты.

Базы здесь нет намеренно: нарезка — чистая функция, и проверять её через
HTTP и Postgres значит платить секундами за то, что считается мгновенно.
"""

from app.services.segmentation import split_block

TARGET = 100
HARD = 200


def cut(text: str) -> list[str]:
    return split_block(text, target_chars=TARGET, hard_limit_chars=HARD)


def test_empty_text_gives_no_segments() -> None:
    assert cut("") == []
    assert cut("   \n\t  ") == []


def test_short_block_stays_whole() -> None:
    assert cut("Короткий абзац.") == ["Короткий абзац."]


def test_whitespace_is_normalized() -> None:
    """Переводы строк внутри абзаца — это вёрстка исходника, а не смысл."""
    assert cut("Первая строка\n   вторая\tстрока") == ["Первая строка вторая строка"]


def test_long_block_splits_on_sentence_boundaries() -> None:
    sentence = "Это предложение средней длины для проверки нарезки. "
    segments = cut(sentence * 6)

    assert len(segments) > 1
    assert all(len(segment) <= TARGET for segment in segments)
    # Границы прошли по точкам: обрывков без завершающего знака нет.
    assert all(segment.endswith(".") for segment in segments)


def test_nothing_is_lost_or_duplicated() -> None:
    text = "Первое предложение. Второе предложение! Третье? Четвёртое. " * 4
    segments = cut(text)

    assert " ".join(segments) == " ".join(text.split())


def test_sentence_longer_than_hard_limit_splits_by_words() -> None:
    text = "слово " * 80  # ни одной точки, 480 знаков
    segments = cut(text)

    assert all(len(segment) <= HARD for segment in segments)
    # Слова целые: ни один сегмент не начинается и не кончается обрубком.
    assert all(word == "слово" for segment in segments for word in segment.split())


def test_single_word_longer_than_limit_is_cut_by_characters() -> None:
    """Последнее средство: границы внутри слова нет, но предел соблюдается."""
    word = "а" * (HARD * 2 + 30)
    segments = cut(word)

    assert all(len(segment) <= HARD for segment in segments)
    assert "".join(segments) == word


def test_quote_after_period_stays_with_sentence() -> None:
    """Закрывающая кавычка принадлежит предложению, а не следующему."""
    text = (
        "Он сказал: «Это конец главы.» Дальше идёт новая мысль, "
        "достаточно длинная, чтобы блок пришлось резать на части. "
    ) * 2
    segments = cut(text)

    assert not any(segment.startswith("»") for segment in segments)
