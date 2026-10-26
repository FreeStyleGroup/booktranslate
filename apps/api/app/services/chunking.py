"""Нарезка блока на части для модели — без потери единого знака.

Блок мастера — неизменяемый текст исходника. Модель же не берёт абзац на
три страницы одним куском, поэтому длинный блок режется. Главное правило
здесь: склеенные части дают ровно текст блока, знак в знак. Прежняя
нарезка схлопывала пробелы, и собрать из её частей исходник было нельзя —
а значит, нельзя и проверить, что модели отдали то, что лежит в мастере.

Отсюда и устройство: части — это отрезки текста, а не переписанные
предложения. Пробел после конца предложения остаётся в хвосте предыдущей
части, а не теряется на стыке.

Режется по границам смысла, от менее разрушительного к более:

1. блок короче цели — одна часть;
2. по концам предложений, набирая их до целевого размера;
3. предложение длиннее жёсткого предела — по пробелам между словами.

Разрыва внутри слова не бывает: слово длиннее предела остаётся одной
частью. Листинги кода не режутся вовсе — разрезанный пример перестаёт
быть примером.

Смена размеров нарезки меняет части, но не блоки: коды блоков от нарезки
не зависят.
"""

import math
import re
from collections.abc import Iterator

from app.models.block import BlockKind

# Конец предложения вместе с пробелами за ним: знак, необязательная
# закрывающая кавычка или скобка, затем пробельные символы. Пробелы входят
# в отрезок — они принадлежат концу предыдущей части.
_SENTENCE_END = re.compile(r"[.!?…][»\"')\]]?\s+")
_SPACE_RUN = re.compile(r"\s+")


def chunk(text: str, kind: BlockKind, *, target_chars: int, hard_limit_chars: int) -> list[str]:
    """Части блока; их склейка всегда равна `text`."""
    if not text:
        return []

    if kind is BlockKind.CODE or len(text) <= target_chars:
        return [text]

    pieces = list(_sentences(text))

    return list(_pack(pieces, target_chars, hard_limit_chars))


def estimate_tokens(text: str, chars_per_token: float) -> int:
    """Сколько токенов займёт часть — оценка сверху, не меньше одного."""
    return max(1, math.ceil(len(text) / chars_per_token))


def _sentences(text: str) -> Iterator[str]:
    start = 0

    for match in _SENTENCE_END.finditer(text):
        yield text[start : match.end()]
        start = match.end()

    if start < len(text):
        yield text[start:]


def _pack(pieces: list[str], target: int, hard_limit: int) -> Iterator[str]:
    current = ""

    for piece in pieces:
        if len(piece) > hard_limit:
            if current:
                yield current
                current = ""
            yield from _by_words(piece, hard_limit)
            continue

        if current and len(current) + len(piece) > target:
            yield current
            current = ""

        current += piece

    if current:
        yield current


def _by_words(text: str, hard_limit: int) -> Iterator[str]:
    """Отрезки не длиннее предела, разрезанные только по пробелам.

    Пробелы на стыке остаются в хвосте предыдущего отрезка. Слово длиннее
    предела не режется — оно выходит одним отрезком, сколько бы ни весило.
    """
    start = 0

    while len(text) - start > hard_limit:
        window_end = start + hard_limit
        cut = None

        for match in _SPACE_RUN.finditer(text, start, window_end + 1):
            if match.end() <= window_end:
                cut = match.end()

        if cut is None or cut <= start:
            # Внутри предела пробела нет: режем по первому пробелу после
            # него, а если и его нет — отдаём остаток целиком.
            following = _SPACE_RUN.search(text, window_end)
            if following is None:
                break
            cut = following.end()

        yield text[start:cut]
        start = cut

    if start < len(text):
        yield text[start:]
