"""Правила порционного перевода — без базы.

Проверяются чистые функции: размер порции, признак зависшего документа и
состояние документа по его сегментам. Именно они решают, продолжится ли
книга после падения контейнера, и ошибка в них не видна по одному
запросу — только по документу, который «уже переводится» неделю.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.document import DocumentStatus
from app.services.errors import InvalidInputError
from app.services.translation import is_stale, page_size, settled_status


def test_page_size_defaults_when_not_requested() -> None:
    """Без значения — умолчание из настроек, а не «всё сразу»."""
    assert page_size(None, default=200, maximum=20000) == 200


def test_page_size_keeps_requested_within_maximum() -> None:
    assert page_size(50, default=200, maximum=20000) == 50
    assert page_size(20000, default=200, maximum=20000) == 20000


def test_page_size_refuses_excess_instead_of_trimming() -> None:
    """Молчаливое урезание обмануло бы цикл клиента, который ждёт столько, сколько просил."""
    with pytest.raises(InvalidInputError):
        page_size(20001, default=200, maximum=20000)


def test_page_size_refuses_nonpositive() -> None:
    with pytest.raises(InvalidInputError):
        page_size(0, default=200, maximum=20000)


def test_stale_after_threshold() -> None:
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    threshold = timedelta(minutes=30)

    assert is_stale(now - timedelta(minutes=31), now=now, threshold=threshold)
    assert is_stale(now - timedelta(minutes=30), now=now, threshold=threshold)
    # Пачка, отмеченная минуту назад, — живой прогон, а не брошенный.
    assert not is_stale(now - timedelta(minutes=1), now=now, threshold=threshold)


def test_settled_status_follows_the_segments() -> None:
    """Состояние после срыва или порции определяется данными, а не тем, «как было»."""
    # Разбор так и не записал сегменты — документ только загружен.
    assert settled_status(total=0, untranslated=0) is DocumentStatus.UPLOADED
    # Остались непереведённые — «разобран»: следующий вызов продолжит.
    assert settled_status(total=100, untranslated=60) is DocumentStatus.PARSED
    assert settled_status(total=100, untranslated=100) is DocumentStatus.PARSED
    # Непереведённых нет — перевод принимает человек.
    assert settled_status(total=100, untranslated=0) is DocumentStatus.REVIEW
