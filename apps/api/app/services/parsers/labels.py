"""Номера объектов в тексте: «Рисунок 3.2», «табл. 1.4», «Eq. (2.1)».

Одни и те же слова нужны в двух местах. Разбор по ним узнаёт подпись —
абзац «Figure 3.2. Loss curve» рядом с картинкой — и решает, к какому
объекту она относится. Поиск упоминаний по ним находит в тексте «см.
рис. 3.2» и связывает блок с рисунком. Разойдись перечни, и подпись
нашлась бы, а упоминание той же подписи — нет.

Слова — английские и русские, с падежами: «на рисунке 3.2», «в
таблице 1.4». Номер — цифры через точку или дефис с необязательной
буквой: «3.2», «3-2», «3.2a».
"""

import re
from dataclasses import dataclass

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.services.parsers.base import Owner, ParsedBlock, ParsedItem, ParsedObject

_WORDS = {
    ObjectType.FIGURE: r"fig(?:ure)?s?\.?|рис\.|рисун(?:ок|ка|ке|ком|ки|ков|кам|ками|ках)",
    ObjectType.TABLE: r"tables?|tab\.|табл\.|таблиц(?:а|ы|е|у|ей|ам|ами|ах)?",
    ObjectType.EQUATION: (
        r"equations?|eqs?\.|формул(?:а|ы|е|у|ой|ам|ами|ах)|уравнени(?:е|я|ю|ем|и|й|ям|ями|ях)"
    ),
    ObjectType.CODE: r"listings?|листинг(?:а|е|у|ом|и|ов|ам|ами|ах)?",
}

_NUMBER = r"\d+(?:[.\-–]\d+)*[a-zа-я]?"

# Номер может стоять в скобках — так нумеруют формулы: «Eq. (3.2)».
_NUMBERED = rf"\(?\s*(?P<number>{_NUMBER})\s*\)?"

_KIND_GROUPS = "|".join(f"(?P<{kind.name}>{words})" for kind, words in _WORDS.items())

# Подпись начинается с номера. После номера — знак препинания или конец
# строки: «Table 3.1 shows…» — фраза о таблице, а «Table 3.1. Results» —
# её подпись. Подпись без знака («Figure 3.2 Loss») разбор принимает
# только у абзаца, размеченного автором как подпись.
_CAPTION = re.compile(
    rf"^\s*(?:{_KIND_GROUPS})\s*{_NUMBERED}(?P<tail>\s*(?:[.:—–-]|$))?",
    re.IGNORECASE,
)

# Упоминание — где угодно в тексте. Перечень номеров через запятую или
# союз — тоже упоминания: «Figures 3.2 and 3.3».
_MENTION = re.compile(
    rf"(?<!\w)(?:{_KIND_GROUPS})\s*(?P<numbers>\(?\s*{_NUMBER}\s*\)?"
    rf"(?:\s*(?:,|and|or|и|или)\s*\(?\s*{_NUMBER}\s*\)?)*)",
    re.IGNORECASE,
)

_NUMBER_ONLY = re.compile(rf"\(?\s*({_NUMBER})\s*\)?")

# Номер формулы, стоящий справа от неё сам по себе: «(3.2)».
EQUATION_NUMBER = re.compile(rf"^\s*\(\s*(?P<number>{_NUMBER})\s*\)\s*$")


@dataclass(frozen=True, slots=True)
class Label:
    type: ObjectType
    number: str
    # После номера стоит знак препинания: так пишут подписи, а не фразы.
    punctuated: bool


@dataclass(frozen=True, slots=True)
class Mention:
    type: ObjectType
    number: str
    # Как объект назван в тексте — «рис. 3.2».
    phrase: str


def normalize_number(number: str) -> str:
    """Номер в одном написании: тире в дефис, буква — строчная."""
    return number.replace("–", "-").lower()


def caption_label(text: str) -> Label | None:
    """Номер объекта в начале подписи, если он там есть."""
    match = _CAPTION.match(text)

    if match is None:
        return None

    return Label(
        type=_kind_of(match),
        number=normalize_number(match.group("number")),
        punctuated=match.group("tail") is not None,
    )


def mentions(text: str) -> list[Mention]:
    """Упоминания объектов в тексте по номерам."""
    found: list[Mention] = []

    for match in _MENTION.finditer(text):
        kind = _kind_of(match)
        phrase = match.group(0).strip()

        found.extend(
            Mention(type=kind, number=normalize_number(number), phrase=phrase)
            for number in _NUMBER_ONLY.findall(match.group("numbers"))
        )

    return found


def bind_captions(items: list[ParsedItem]) -> None:
    """Привязать к объектам подписи, стоящие рядом с ними, а не внутри.

    В DOCX подпись — отдельный абзац перед таблицей или после рисунка, в
    EPUB бывает `<p class="caption">` под картинкой. Подписью считается
    блок, размеченный автором как подпись, или абзац, который начинается с
    номера объекта и знака после него: «Figure 3.2. Loss curve».

    Подпись встаёт к соседнему объекту — тому, что прямо перед ней, или
    тому, что прямо после. Номер в подписи называет вид, и с объектом
    другого вида она не свяжется. Таблицу подписывают сверху, рисунок —
    снизу, поэтому таблица ищется сначала после подписи, остальное — до.
    """
    captioned = {
        item.owner.object
        for item in items
        if isinstance(item, ParsedBlock) and item.owner is not None and item.owner.caption
    }

    for index, item in enumerate(items):
        if not isinstance(item, ParsedBlock) or item.owner is not None:
            continue

        label = caption_label(item.text)
        declared = item.kind is BlockKind.CAPTION

        if not declared and (label is None or not label.punctuated):
            continue

        target = _neighbour(items, index, label, captioned)
        if target is None:
            continue

        item.owner = Owner(object=target, caption=True)
        item.kind = BlockKind.CAPTION
        captioned.add(target)


def _neighbour(
    items: list[ParsedItem], index: int, label: Label | None, captioned: set[ParsedObject]
) -> ParsedObject | None:
    before = _object_at(items, index - 1)
    after = items[index + 1] if index + 1 < len(items) else None
    after = after if isinstance(after, ParsedObject) else None

    order = (
        (after, before) if label is not None and label.type is ObjectType.TABLE else (before, after)
    )

    return next(
        (
            candidate
            for candidate in order
            if candidate is not None
            and candidate not in captioned
            and (label is None or candidate.type is label.type)
        ),
        None,
    )


def _object_at(items: list[ParsedItem], index: int) -> ParsedObject | None:
    """Объект на месте: сам объект или блок-содержимое объекта — ячейка, листинг."""
    if index < 0:
        return None

    item = items[index]

    if isinstance(item, ParsedObject):
        return item

    if item.owner is not None and not item.owner.caption:
        return item.owner.object

    return None


def _kind_of(match: re.Match[str]) -> ObjectType:
    return next(kind for kind in ObjectType if match.group(kind.name) is not None)
