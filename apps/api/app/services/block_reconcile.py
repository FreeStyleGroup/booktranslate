"""Сопоставление глав и блоков с новым разбором исходника.

Две задачи, обе — чистые функции над уже разобранным потоком блоков.

**Где глава в новом разборе.** Границы главы сохранены номерами блоков,
но номера верны только для той версии разбора, при которой их
утверждали. Исправили разборщик — и всё, что после исправления, могло
сдвинуться. Поэтому при извлечении мастера глава находится заново — по
якорям: своему заголовку, файлу EPUB или странице PDF. Сохранённый номер
служит подсказкой, какое из одинаковых вхождений выбрать.

**Какие блоки остались прежними.** Новая версия мастера сопоставляется с
прежней по хешу вида и текста блока, с сохранением порядка. Совпавшие
блоки сохраняют коды — это требование процесса: повторный разбор не
меняет кодов неизменившихся блоков. Изменённые получают новые коды и
ссылку на блок, из которого получились; исчезнувшие выводятся из
действия. Прежний код не переиспользуется никогда.

Объекты сопоставляются тем же способом — по виду и контрольной сумме
содержимого.
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.services.parsers import ParsedBlock

# Предел длины названия раздела — от колонки названия главы. Заголовок
# длиннее — почти всегда склеенный абзац, и хранить его целиком незачем.
TITLE_MAX = 500


def heading_title(text: str) -> str:
    """Название раздела из текста заголовка — одна строка, не длиннее предела.

    Одно правило на предложение глав и на поиск их якорей: разойдись они,
    и раздел с длинным заголовком не нашёлся бы в собственной книге.
    """
    return " ".join(text.split())[:TITLE_MAX]


class AnchorNotFoundError(Exception):
    """Якорь главы не найден в новом разборе: заголовок исчез или изменился."""


def block_hash(kind: BlockKind, text: str) -> str:
    """Хеш блока — вид вместе с текстом.

    Вид входит в хеш: строка, ставшая из абзаца заголовком, — другой блок,
    и сохранить ему прежний код со старым видом значило бы соврать.
    """
    return hashlib.sha256(f"{kind.value}\n{text}".encode()).hexdigest()


def object_hash(type_: ObjectType, checksum: str) -> str:
    """Хеш объекта для сопоставления — вид вместе с суммой содержимого."""
    return hashlib.sha256(f"{type_.value}\n{checksum}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PlacedEntry:
    """Объект версии в том виде, в каком он входит в её сумму."""

    type: ObjectType
    checksum: str
    # Место и состав — номерами блоков версии, а не их идентификаторами:
    # сумма считается по содержимому, и одинаковая глава обязана давать
    # одинаковую сумму, кто бы и когда её ни извлёк.
    at: int
    content: tuple[int, ...]
    caption: int | None


def master_checksum(blocks: Sequence[tuple[BlockKind, str]], objects: Sequence[PlacedEntry]) -> str:
    """Контрольная сумма версии мастера — по блокам и объектам в порядке.

    Каноническая сериализация — JSON без пробелов: одинаковое содержимое
    обязано давать одинаковую сумму на любой машине.
    """
    payload = json.dumps(
        {
            "blocks": [[kind.value, text] for kind, text in blocks],
            "objects": [
                [entry.type.value, entry.checksum, entry.at, list(entry.content), entry.caption]
                for entry in objects
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(payload.encode()).hexdigest()


def locate(
    blocks: Sequence[ParsedBlock],
    *,
    first_section: dict[str, Any],
    previous_start: int,
    following_section: dict[str, Any] | None,
    following_start: int | None,
) -> tuple[int, int]:
    """Границы главы в новом разборе: начало включительно, конец — нет.

    Начало — якорь первого раздела главы. Конец — якорь первого раздела
    следующей главы, а у последней главы — конец книги.
    """
    start = _anchor(blocks, first_section, near=previous_start, after=0)

    if following_section is None or following_start is None:
        end = len(blocks)
    else:
        end = _anchor(blocks, following_section, near=following_start, after=start + 1)

    if end <= start:
        raise AnchorNotFoundError("Границы главы в новом разборе пусты")

    return start, end


@dataclass(frozen=True, slots=True)
class Existing:
    """Блок или объект прежней версии мастера — то, что нужно для сопоставления."""

    id: uuid.UUID
    source_hash: str
    # Текст нужен, чтобы узнать разделение: прежний блок равен склейке
    # нескольких новых. У объекта текста нет — объекты не делятся.
    source_text: str | None


@dataclass(frozen=True, slots=True)
class Fresh:
    """Блок или объект нового разбора — то же для другой стороны."""

    source_hash: str
    source_text: str | None


@dataclass(frozen=True, slots=True)
class Keep:
    """Блок не изменился: тот же код, новое место."""

    existing: int
    parsed: int


@dataclass(frozen=True, slots=True)
class Create:
    """Новый блок. `parent` — блок, из которого он получился, если такой ясен."""

    parsed: int
    parent: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class Retire:
    """Блока больше нет в тексте главы: выводится из действия, но остаётся."""

    existing: int


Step = Keep | Create | Retire


def reconcile(existing: Sequence[Existing], parsed: Sequence[ParsedBlock]) -> list[Step]:
    """Как прежние блоки главы соотносятся с новым разбором."""
    return match(
        existing, [Fresh(block_hash(block.kind, block.text), block.text) for block in parsed]
    )


def match(existing: Sequence[Existing], fresh: Sequence[Fresh]) -> list[Step]:
    """Как прежние блоки или объекты главы соотносятся с новым разбором.

    Сопоставление с сохранением порядка по хешу: одинаковый абзац,
    переехавший в другое место, считается удалённым и добавленным, а не
    перенесённым — порядок блоков в главе тоже содержание.

    Родство устанавливается внутри каждого участка замены — см.
    `_lineage`. Соседние правки алгоритм сравнения сливает в один участок,
    и правило «один прежний — его и предок» там уже не работает.
    """
    matcher = SequenceMatcher(
        a=[item.source_hash for item in existing],
        b=[item.source_hash for item in fresh],
        autojunk=False,
    )
    steps: list[Step] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            steps.extend(
                Keep(existing=i, parsed=j)
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            )
            continue

        parents = (
            _lineage(existing[i1:i2], fresh[j1:j2]) if tag == "replace" else [None] * (j2 - j1)
        )
        steps.extend(Retire(existing=i) for i in range(i1, i2))
        steps.extend(
            Create(parsed=j, parent=parent)
            for j, parent in zip(range(j1, j2), parents, strict=True)
        )

    return steps


def _lineage(old: Sequence[Existing], new: Sequence[Fresh]) -> list[uuid.UUID | None]:
    """Предок каждого нового блока участка замены — или ничего.

    По убыванию уверенности:

    1. разделение — прежний блок равен подряд идущим новым, склеенным без
       учёта пробелов на стыках (у объектов текста нет, и разделения
       тоже);
    2. правка на месте — оставшихся прежних и новых поровну: пары по
       порядку;
    3. остался один прежний — он предок всех оставшихся новых;
    4. иначе родство не выдумывается: кто из кого получился, не видно.
    """
    parents: list[uuid.UUID | None] = [None] * len(new)
    squeezed = ["".join((item.source_text or "").split()) for item in new]
    used_old: set[int] = set()
    cursor = 0

    for index, item in enumerate(old):
        if item.source_text is None:
            continue

        target = "".join(item.source_text.split())

        for start in range(cursor, len(new)):
            for stop in range(start + 2, len(new) + 1):
                if "".join(squeezed[start:stop]) == target:
                    parents[start:stop] = [item.id] * (stop - start)
                    used_old.add(index)
                    cursor = stop
                    break
            if index in used_old:
                break

    rest_old = [item for index, item in enumerate(old) if index not in used_old]
    rest_new = [index for index, parent in enumerate(parents) if parent is None]

    if len(rest_old) == len(rest_new):
        for item, index in zip(rest_old, rest_new, strict=True):
            parents[index] = item.id
    elif len(rest_old) == 1:
        for index in rest_new:
            parents[index] = rest_old[0].id

    return parents


def _anchor(
    blocks: Sequence[ParsedBlock], section: dict[str, Any], *, near: int, after: int
) -> int:
    """Номер блока, с которого начинается раздел, в новом разборе.

    Заголовок ищется по тексту; из одинаковых выбирается ближайший к
    прежнему месту — в книге бывают два «Введения», и брать первое
    попавшееся значило бы перепутать главы. Раздел без заголовка — по
    файлу EPUB или странице PDF. Без того и другого остаётся прежний номер:
    так выглядит только начало книги до первого заголовка.
    """
    title = section.get("title")
    locator: dict[str, Any] = section.get("locator") or {}

    if title is not None:
        candidates = [
            index
            for index in range(after, len(blocks))
            if blocks[index].kind is BlockKind.HEADING
            and heading_title(blocks[index].text) == title
        ]
    elif "href" in locator or "page" in locator:
        key = "href" if "href" in locator else "page"
        candidates = [
            index
            for index in range(after, len(blocks))
            if blocks[index].location.get(key) == locator[key]
            and (index == 0 or blocks[index - 1].location.get(key) != locator[key])
        ]
    else:
        candidates = [near] if after <= near < len(blocks) else []

    if not candidates:
        raise AnchorNotFoundError(
            f"В новом разборе не найден раздел «{title}»"
            if title is not None
            else "В новом разборе не найдено начало главы"
        )

    return min(candidates, key=lambda index: abs(index - near))
