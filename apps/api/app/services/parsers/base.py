"""Что разборщик отдаёт наружу.

Разборщик формата не знает ни про базу, ни про сегменты: он превращает файл
в последовательность блоков — абзацев, заголовков, пунктов списка, ячеек
таблицы — и специальных объектов: рисунков, таблиц, формул, листингов.
Нарезка блока на части и запись в базу происходят дальше и одинаково для
всех форматов, поэтому здесь их нет.

Такое разделение позволяет проверять разбор DOCX без базы и без FastAPI:
на входе файл, на выходе поток блоков и объектов.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.models.block import BlockKind
from app.models.book_object import ObjectType


@dataclass(frozen=True, slots=True)
class ImageSource:
    """Откуда взять байты изображения.

    Разбор их не читает: книге с сотней иллюстраций незачем держать их в
    памяти, пока предлагаются главы. Байты нужны только при извлечении
    мастера, и только той главы, которую извлекают.
    """

    # Файл внутри архива исходника — EPUB и DOCX это ZIP.
    member: str | None = None
    # Изображение прямо в разметке — SVG внутри XHTML.
    data: bytes | None = None
    # Путь, как он записан в исходнике, и замещающий текст.
    src: str | None = None
    alt: str | None = None


@dataclass(slots=True, eq=False)
class ParsedObject:
    """Специальный объект исходника: рисунок, таблица, формула, листинг.

    Сравнивается по тождеству, а не по полям: на объект ссылаются его
    блоки, и два одинаковых рисунка в разных местах — два разных объекта.
    """

    type: ObjectType
    location: dict[str, Any] = field(default_factory=dict)
    # То, чего нет в блоках: сетка таблицы, запись формулы, язык листинга.
    payload: dict[str, Any] = field(default_factory=dict)
    images: tuple[ImageSource, ...] = ()
    # Номер, известный из самого объекта, а не из подписи: «(3.2)» справа
    # от формулы.
    label: str | None = None
    # Якоря, по которым на объект ведут гиперссылки: `ch03.xhtml#fig3-2`.
    anchors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Owner:
    """Объект, которому принадлежит блок, и в каком качестве."""

    object: ParsedObject
    # Подпись, а не содержимое: содержимое — ячейки таблицы и текст
    # листинга, подпись — одна на объект.
    caption: bool = False


@dataclass(slots=True)
class ParsedBlock:
    """Смысловая единица исходника до нарезки на части."""

    text: str
    kind: BlockKind = BlockKind.PARAGRAPH

    # Где блок стоял в исходнике: номер главы у EPUB, строка у Markdown,
    # координаты ячейки у таблицы. Структура свободная — у каждого формата
    # она своя, а заводить под каждый свои колонки значит плодить пустоты.
    location: dict[str, Any] = field(default_factory=dict)

    # Объект, частью которого блок является. Ячейка таблицы переводится
    # как текст, но стоит в сетке; листинг не переводится вовсе.
    owner: Owner | None = None


ParsedItem = ParsedBlock | ParsedObject


class DocumentParser(Protocol):
    """Разборщик одного семейства форматов."""

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        """Прочитать файл и отдать блоки и объекты в порядке следования.

        Генератор, а не список: книга на тысячу страниц не обязана целиком
        помещаться в память, а вызывающий код всё равно обрабатывает блоки
        по одному.

        Объект отдаётся раньше своих блоков — тем местом, где он начинается.
        """
        ...


class ParsingError(Exception):
    """Файл не удалось разобрать: битый контейнер, неизвестная разметка.

    Отдельный тип нужен, чтобы отличить «формат не поддерживается» (об этом
    известно до чтения) от «файл заявлен как DOCX, но внутри мусор».
    """


def blocks_of(items: Iterable[ParsedItem]) -> Iterator[ParsedBlock]:
    """Только блоки — тем, кому объекты не нужны: предложению глав, проверке файла."""
    return (item for item in items if isinstance(item, ParsedBlock))


@dataclass(frozen=True, slots=True)
class PlacedObject:
    """Объект и его место в потоке блоков."""

    object: ParsedObject
    # Сколько блоков стоит перед объектом.
    at: int
    # Номера блоков-содержимого и блока подписи в потоке.
    content: tuple[int, ...]
    caption: int | None


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """Разобранный файл: блоки по порядку и объекты с местами среди них.

    Номер блока — его место в потоке; тот же номер получат границы глав.
    Объекты блоков не сдвигают.
    """

    blocks: list[ParsedBlock]
    objects: list[PlacedObject]


def collect(items: Iterable[ParsedItem]) -> ParsedSource:
    """Разложить поток разбора на блоки и объекты с местами."""
    blocks: list[ParsedBlock] = []
    places: dict[ParsedObject, int] = {}

    for item in items:
        if isinstance(item, ParsedObject):
            places[item] = len(blocks)
        else:
            blocks.append(item)

    content: dict[ParsedObject, list[int]] = {item: [] for item in places}
    captions: dict[ParsedObject, int] = {}

    for index, block in enumerate(blocks):
        if block.owner is None:
            continue

        owner = block.owner.object
        if owner not in places:
            raise ParsingError("Блок ссылается на объект, которого нет в разборе")

        if block.owner.caption and owner not in captions:
            captions[owner] = index
        else:
            content[owner].append(index)

    return ParsedSource(
        blocks=blocks,
        objects=[
            PlacedObject(
                object=item,
                at=at,
                content=tuple(content[item]),
                caption=captions.get(item),
            )
            for item, at in places.items()
        ],
    )
