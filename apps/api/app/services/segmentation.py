"""Нарезка блоков на сегменты.

Блок исходника и сегмент перевода — не одно и то же. Абзац на три страницы
переводить одним куском нельзя: он не влезет в окно модели, а редактору
придётся вычитывать всё целиком ради одной правки. Поэтому длинные блоки
режутся, и режутся по границам смысла, а не по счётчику знаков.

Порядок попыток — от менее разрушительной к более:

1. блок короче цели — оставляем как есть;
2. режем по границам предложений и набираем их до целевого размера;
3. предложение само длиннее жёсткого предела (сплошной текст без точек,
   таблица, выгрузка) — режем по словам.

Разрыв внутри слова не делается никогда: склеить перевод обратно из половин
слова невозможно.
"""

import re
from collections.abc import Iterator

# Граница предложения — пробел после точки, восклицательного или
# вопросительного знака. Два варианта, а не один с необязательной кавычкой:
# закрывающая кавычка принадлежит закончившемуся предложению, и граница
# проходит ЗА ней. Иначе сегмент начинался бы с осиротевшей «»».
#
# Оба просмотра назад фиксированной длины — переменная длина в re запрещена,
# и обойти это можно только перечислением.
#
# Сокращения вроде «т. е.» этим выражением тоже разрежутся; для нарезки на
# сегменты это безобидно (обе половины всё равно переводятся подряд), а
# полноценный разборщик предложений тянет словарь сокращений на каждый язык.
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?…])(?=\s)|(?<=[.!?…][»"\')\]])(?=\s)')

_WHITESPACE = re.compile(r"\s+")


def split_block(text: str, *, target_chars: int, hard_limit_chars: int) -> list[str]:
    """Разрезать текст блока на сегменты.

    Пустой или состоящий из пробелов текст даёт пустой список: сегмент без
    содержимого нечего переводить и незачем показывать.
    """
    normalized = _WHITESPACE.sub(" ", text).strip()
    if not normalized:
        return []

    if len(normalized) <= target_chars:
        return [normalized]

    return list(_pack(_sentences(normalized), target_chars, hard_limit_chars))


def _sentences(text: str) -> Iterator[str]:
    for part in _SENTENCE_BOUNDARY.split(text):
        candidate = part.strip()
        if candidate:
            yield candidate


def _pack(sentences: Iterator[str], target: int, hard_limit: int) -> Iterator[str]:
    """Набрать предложения в сегменты, не превышая целевой размер."""
    current = ""

    for sentence in sentences:
        # Предложение не помещается даже одно — режем его по словам, а
        # накопленное отдаём до этого, чтобы не смешать с обрывками.
        if len(sentence) > hard_limit:
            if current:
                yield current
                current = ""

            yield from _split_by_words(sentence, hard_limit)
            continue

        candidate = f"{current} {sentence}" if current else sentence
        if len(candidate) <= target:
            current = candidate
            continue

        if current:
            yield current

        current = sentence

    if current:
        yield current


def _split_by_words(text: str, hard_limit: int) -> Iterator[str]:
    """Последнее средство: набрать по словам до жёсткого предела."""
    current = ""

    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= hard_limit:
            current = candidate
            continue

        if current:
            yield current
            current = ""

        if len(word) <= hard_limit:
            current = word
            continue

        # Слово длиннее предела целиком (склейка без пробелов, длинный URL):
        # режем по знакам — других границ здесь нет. Хвост короче предела
        # остаётся в current и достанется следующим словам.
        for start in range(0, len(word), hard_limit):
            chunk = word[start : start + hard_limit]
            if len(chunk) == hard_limit:
                yield chunk
            else:
                current = chunk

    if current:
        yield current
