"""Защищённое содержимое: то, что модель не имеет права переформулировать.

Формула в строке, кусок кода, подстановка `{0}`, адрес ссылки — всё это внутри
обычной фразы и переводу не подлежит. Просьба в промпте «сохрани как есть»
не гарантия: модель перепишет индекс, поправит регистр или переведёт имя
переменной и ничем себя не выдаст. Поэтому она их просто не видит: вместо
содержимого в запрос идёт заменитель `⟦1⟧`, а содержимое возвращается на место
знак в знак уже после ответа.

Заменитель в ответе обязан встретиться ровно столько раз, сколько в запросе.
Потерянная формула — не повод вернуть фразу без неё: такой ответ отвергается.

Чистый код: строка на входе, строка на выходе. Без базы и без модели.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

TOKEN = re.compile(r"⟦(\d+)⟧")
_TOKEN_EDGE = "⟦"

# Кроме того, что отметил разбор (см. `Block.source_location["protected"]`),
# защищается то, что узнаётся по самому тексту в любом формате.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code", re.compile(r"`[^`\n]+`")),
    ("url", re.compile(r"\bhttps?://[^\s<>\"'»)\]]+")),
    (
        "placeholder",
        re.compile(
            r"\{[^{}\n]{0,60}\}"  # {0}, {name}
            r"|%\([A-Za-z_]\w*\)[sdif]"  # %(name)s
            r"|%[-+ #0-9.]*[sdifgxX]\b"  # %s, %d, %.2f
            r"|</?[A-Za-z][^<>\n]{0,80}>"  # <b>, <br/>
        ),
    ),
)


class TokenMismatchError(Exception):
    """Заменители в ответе не совпали с отправленными."""

    def __init__(self, *, lost: Sequence[str], extra: Sequence[str]) -> None:
        self.lost = list(lost)
        self.extra = list(extra)

        details = []
        if lost:
            details.append("потеряно: " + ", ".join(lost))
        if extra:
            details.append("лишнее: " + ", ".join(extra))

        super().__init__("Модель не сохранила защищённое содержимое — " + "; ".join(details))


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    kind: str


@dataclass(frozen=True, slots=True)
class Masked:
    """Текст для модели и то, что вернуть на место."""

    text: str
    # Содержимое заменителей: первый элемент — `⟦1⟧`.
    originals: tuple[str, ...] = ()


def stored_spans(
    location: dict[str, Any], *, offset: int = 0, length: int | None = None
) -> list[Span]:
    """Что разбор отметил как защищённое — в координатах куска блока.

    Кусок — часть блока, идущая в модель. Отметка, не поместившаяся в кусок
    целиком, обрезается по его границам: каждая половина остаётся защищённой.
    """
    raw = location.get("protected")
    if not isinstance(raw, list):
        return []

    end_of_piece = None if length is None else offset + length
    spans = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        start, end, kind = item.get("start"), item.get("end"), item.get("kind")

        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(kind, str):
            continue

        begin = max(start, offset)
        stop = end if end_of_piece is None else min(end, end_of_piece)

        if begin < stop:
            spans.append(Span(begin - offset, stop - offset, kind))

    return spans


def find_spans(text: str, known: Iterable[Span] = ()) -> list[Span]:
    """Все защищённые участки текста — по порядку и без пересечений.

    Отмеченное разбором важнее найденного по виду: `<code>{x}</code>` — один
    кусок кода, а не код с подстановкой внутри.
    """
    spans = list(known)

    for kind, pattern in _PATTERNS:
        spans.extend(Span(match.start(), match.end(), kind) for match in pattern.finditer(text))

    chosen: list[Span] = []
    # Раньше начавшийся и более длинный выигрывает: `{a}` внутри адреса — часть
    # адреса, а не отдельная подстановка.
    for span in sorted(spans, key=lambda item: (item.start, -(item.end - item.start))):
        if not chosen or span.start >= chosen[-1].end:
            chosen.append(span)

    return chosen


def mask(text: str, spans: Sequence[Span]) -> Masked:
    """Заменить защищённые участки заменителями.

    Текст, в котором уже встречается знак заменителя, не трогается: сверить
    такой ответ было бы не с чем, и ложный отказ хуже незащищённой фразы из
    книги о самих этих скобках.
    """
    if not spans or _TOKEN_EDGE in text:
        return Masked(text=text)

    parts: list[str] = []
    originals: list[str] = []
    cursor = 0

    for number, span in enumerate(spans, start=1):
        parts.append(text[cursor : span.start])
        parts.append(f"⟦{number}⟧")
        originals.append(text[span.start : span.end])
        cursor = span.end

    parts.append(text[cursor:])

    return Masked(text="".join(parts), originals=tuple(originals))


def unmask(answer: str, masked: Masked) -> str:
    """Вернуть содержимое на место, проверив заменители.

    Порядок заменителей в ответе свободен: в языке перевода формула законно
    встаёт в другое место фразы.
    """
    # Исходник сам содержит такие скобки — заменителей в него не ставили.
    if not masked.originals and _TOKEN_EDGE in masked.text:
        return answer

    found = Counter(int(match.group(1)) for match in TOKEN.finditer(answer))
    expected = Counter(range(1, len(masked.originals) + 1))

    if found != expected:
        raise TokenMismatchError(
            lost=[f"⟦{number}⟧" for number in sorted((expected - found).elements())],
            extra=[f"⟦{number}⟧" for number in sorted((found - expected).elements())],
        )

    return TOKEN.sub(lambda match: masked.originals[int(match.group(1)) - 1], answer)


def join_pieces(sources: Sequence[str], answers: Sequence[str]) -> str:
    """Собрать перевод блока из переводов его кусков.

    Разделитель между кусками принадлежит исходнику: склейка кусков — текст
    блока знак в знак, поэтому пробел или перевод строки на границе у куска
    свой. Модель отвечает без них, и они возвращаются отсюда.
    """
    parts = []

    for source, answer in zip(sources, answers, strict=True):
        head = source[: len(source) - len(source.lstrip())]
        tail = source[len(source.rstrip()) :]
        parts.append(f"{head}{answer.strip()}{tail}")

    return "".join(parts)
