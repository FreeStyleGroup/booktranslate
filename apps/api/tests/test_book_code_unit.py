"""Код издания — запись его номера, без базы."""

from app.models.book import BookEdition


def test_code_is_two_digits_within_first_hundred() -> None:
    assert BookEdition(number=1).code == "BK01"
    assert BookEdition(number=99).code == "BK99"


def test_code_has_no_two_digit_ceiling() -> None:
    """Сотая книга получает «BK100», а не обрезанный или повторённый код."""
    assert BookEdition(number=100).code == "BK100"
