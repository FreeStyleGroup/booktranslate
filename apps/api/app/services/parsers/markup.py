"""HTML и EPUB.

EPUB — это ZIP с набором XHTML-файлов и описью, в каком порядке их читать.
Поэтому оба формата разбираются одним кодом: EPUB добавляет к HTML только
распаковку и порядок глав.

Кроме блоков разметка даёт объекты: `<figure>`, `<table>`, `<pre>`,
выносную формулу `<math>`, изображение `<img>` и `<svg>`. Объект встаёт в
поток там, где начинается, а блоки внутри него — ячейки, листинг,
`<figcaption>` — помечаются как его.

Опись читается по-настоящему, а не подменяется сортировкой имён файлов:
в книгах главы сплошь и рядом называются `part0012.xhtml`, и алфавитный
порядок ставит одиннадцатую главу между первой и второй.
"""

import base64
import binascii
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

# Только тип узла: разбор идёт через defusedxml ниже, а объекты он
# возвращает штатные. Импортировать ради аннотации сам разбор было бы
# приглашением случайно им воспользоваться.
from xml.etree.ElementTree import Element

from bs4 import BeautifulSoup, CData, Tag

# NavigableString и PageElement пакет bs4 наружу не переэкспортирует —
# строгая типизация принимает их только из модуля, где они определены.
from bs4.element import NavigableString, PageElement

# Не штатный xml.etree: описи приходят из чужого файла, а штатный разбор
# разворачивает рекурсивно вложенные сущности («billion laughs») в гигабайты
# памяти. Термбазы разбираются так же (services/dictionaries/tbx.py).
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.services.parsers.archives import ArchiveTooLargeError, check_archive, read_member
from app.services.parsers.base import (
    ImageSource,
    Owner,
    ParsedBlock,
    ParsedItem,
    ParsedObject,
    ParsingError,
)
from app.services.parsers.formulas import mathml_payload
from app.services.parsers.labels import EQUATION_NUMBER, bind_captions, normalize_number
from app.services.parsers.plain import read_text

# Теги, дающие отдельный блок. Всё, что не перечислено (span, em, a),
# остаётся внутри блока — это оформление внутри предложения, а не граница.
#
# Перечень открыт наружу намеренно: сборка переведённого документа обходит
# разметку тем же списком, и разойтись они не могут — иначе переводы встанут
# не в свои абзацы.
BLOCK_KINDS = {
    "h1": BlockKind.HEADING,
    "h2": BlockKind.HEADING,
    "h3": BlockKind.HEADING,
    "h4": BlockKind.HEADING,
    "h5": BlockKind.HEADING,
    "h6": BlockKind.HEADING,
    "p": BlockKind.PARAGRAPH,
    "li": BlockKind.LIST_ITEM,
    "td": BlockKind.TABLE_CELL,
    "th": BlockKind.TABLE_CELL,
    "figcaption": BlockKind.CAPTION,
    "caption": BlockKind.CAPTION,
    "blockquote": BlockKind.PARAGRAPH,
    "pre": BlockKind.CODE,
}

HEADING_LEVELS = {f"h{level}": level for level in range(1, 7)}

# Теги, текст которых — содержимое знак в знак, а не форматирование.
VERBATIM_TAGS = frozenset({"pre"})

# Надписи внутри SVG — часть рисунка, а не текст главы: их перевод — это
# перерисовка изображения, а не абзац рядом с ним.
_PICTURE_TAGS = frozenset({"svg"})

# Элементы, с которых начинается объект, — в порядке документа.
OBJECT_TAGS = ["figure", "table", "pre", "math", "img", "svg"]

# Подпись объекта — прямой ребёнок его обёртки или таблицы.
CAPTION_TAGS = frozenset({"figcaption", "caption"})

# Предел объединения ячеек — см. `_span`.
MAX_SPAN = 100

# Пробельные символы HTML — без неразрывного пробела: тот в тексте
# поставлен нарочно («10 bar» не должно разорваться) и остаётся собой.
_HTML_SPACE = re.compile(r"[ \t\n\r\f]+")
_SPACE_RUN = re.compile(r" {2,}")
_LINE_EDGE = re.compile(r" *\n *")

_LANGUAGE = re.compile(r"^(?:language|lang)-([\w+#.-]+)$", re.IGNORECASE)

# Открывающий, закрывающий или пустой тег `<svg>` — для вырезки исходной
# разметки рисунка.
_SVG_TAG = re.compile(r"<(?P<close>/)?svg\b[^>]*?(?P<self>/)?>", re.IGNORECASE)

# Служебное содержимое: разметка, стили, скрипты. Переводить его нечего, а
# попав в сегменты, оно ломает и оценку объёма, и счёт денег.
IGNORED_TAGS = {"script", "style", "head", "title", "meta", "link", "noscript"}

# Список для поиска по разметке. Отдельным именем, чтобы вызывающему не
# приходилось помнить, что ключи словаря — это и есть теги.
BLOCK_TAGS = list(BLOCK_KINDS)

# Узлы, из которых складывается текст блока. Ровно те, что берёт
# `get_text()`: комментарий, скрипт и стиль в bs4 — тоже подклассы
# NavigableString, поэтому сравнение по точному типу, а не isinstance.
_TEXT_TYPES = (NavigableString, CData)

_XHTML_SUFFIXES = (".xhtml", ".html", ".htm")


def find_blocks(soup: BeautifulSoup) -> list[Tag]:
    """Целевые блоки разметки в порядке документа.

    Один обход на разбор и на сборку. Номер блока в этом обходе —
    единственное, что связывает сегмент с местом в файле, и любое
    расхождение ставит перевод не в свой абзац, а всё, что дальше по главе,
    сдвигает на один. Поэтому служебные теги здесь не удаляются (сборка
    обязана вернуть их заказчику нетронутыми), а не замечаются: их текст в
    счёт не идёт, а блок внутри них — не вложенный.
    """
    root = soup.body or soup
    blocks: list[Tag] = []

    for element in root.find_all(BLOCK_TAGS):
        if not isinstance(element, Tag):
            continue

        if _under_ignored(element, root):
            continue

        # Вложенный блок отдаётся сам по себе; родитель, который его
        # содержит, не должен выдать его текст второй раз.
        if any(
            not _under_ignored(nested, element)
            for nested in element.find_all(BLOCK_TAGS)
            if isinstance(nested, Tag)
        ):
            continue

        if not block_text(element):
            continue

        # Абзац из одной формулы — это формула, а не текст: её не
        # переводят, а разбор отдаёт её объектом.
        if is_formula_only(element):
            continue

        blocks.append(element)

    return blocks


def is_formula_only(element: Tag) -> bool:
    """Весь текст блока — формулы, разве что с номером справа: «(3.2)»."""
    if element.find("math") is None:
        return False

    outside = "".join(
        str(node)
        for node in block_strings(element)
        if not any(parent.name == "math" for parent in _parents_within(node, element))
    ).strip()

    return not outside or EQUATION_NUMBER.match(outside) is not None


def _parents_within(node: PageElement, stop: Tag) -> Iterator[Tag]:
    for parent in node.parents:
        if parent is stop:
            return
        yield parent


def block_strings(element: Tag) -> list[NavigableString]:
    """Текстовые узлы блока — те, из которых складывается текст сегмента.

    Отдаются сами узлы, а не строки: сборке нужно вписать перевод на место
    ровно тех узлов, которые разбор прочитал, не трогая картинки и ссылки
    между ними.
    """
    return [
        node
        for node in element.descendants
        if isinstance(node, NavigableString)
        and type(node) in _TEXT_TYPES
        and not _under_ignored(node, element)
        and not _inside_object(node, element)
    ]


def _inside_object(node: PageElement, stop: Tag) -> bool:
    """Узел — надпись рисунка SVG или часть выносной формулы.

    Такой текст в блок не входит: рисунок и формула — объекты, и их текст
    не переводится как абзац. Формула в строке (`<math>` без
    `display="block"`) остаётся в тексте абзаца: без неё фраза «где r —
    радиус» теряет смысл.
    """
    return any(
        parent.name in _PICTURE_TAGS or (parent.name == "math" and parent.get("display") == "block")
        for parent in _parents_within(node, stop)
    )


def block_text(element: Tag) -> str:
    """Текст блока таким, каким его показывает браузер, — без служебных тегов.

    Текстовые узлы соединяются как есть, а пробельные символы HTML —
    пробел, табуляция, переводы строк — схлопываются в один пробел: в
    разметке они оформление файла, а не текст, и браузер их так и
    показывает. Неразрывный пробел остаётся собой. `<br>` — перевод
    строки. Соединять узлы пробелом нельзя: «Table <a>1.1</a>.» стало бы
    «Table 1.1 .» — мастер обязан быть текстом книги, а не его пересказом.

    В `<pre>` иначе: отступ в листинге и есть содержимое, и текст берётся
    знак в знак.
    """
    if element.name in VERBATIM_TAGS:
        return _verbatim_text(element)

    strings = {id(node) for node in block_strings(element)}
    parts: list[str] = []

    for node in element.descendants:
        if id(node) in strings:
            parts.append(_HTML_SPACE.sub(" ", str(node)))
        elif isinstance(node, Tag) and node.name == "br" and not _under_ignored(node, element):
            parts.append("\n")

    text = _SPACE_RUN.sub(" ", "".join(parts))

    return _LINE_EDGE.sub("\n", text).strip(" \n")


def _verbatim_text(element: Tag) -> str:
    """Текст `<pre>` как есть: отступы, пустые строки и табуляция на месте.

    Срезается только то, что по правилам HTML содержимым не является:
    перевод строки сразу после открывающего тега и переводы строк перед
    закрывающим. Листинг из одних пробелов — пустой блок.
    """
    text = "".join(str(node) for node in block_strings(element))
    text = text.removeprefix("\r\n").removeprefix("\n").rstrip("\r\n")

    return text if text.strip() else ""


def _under_ignored(node: PageElement, stop: Tag) -> bool:
    """Стоит ли между узлом и `stop` служебный тег (сам `stop` не в счёт)."""
    for parent in node.parents:
        if parent is stop:
            return False

        if parent.name in IGNORED_TAGS:
            return True

    return False


def blocks_from_html(markup: str, location: dict[str, Any] | None = None) -> Iterator[ParsedItem]:
    """Разобрать разметку в блоки и объекты — в порядке документа.

    Используется штатный `html.parser`: он всегда есть в поставке Python и не
    требует бинарной сборки. Битую разметку он чинит менее охотно, чем lxml,
    но в книгах она в основном валидная.
    """
    soup = BeautifulSoup(markup, "html.parser")
    root = soup.body or soup
    base = dict(location or {})
    href: str | None = base.get("href")

    # Место каждого узла в документе: по нему объекты встают между блоками.
    order = {id(node): index for index, node in enumerate(root.descendants)}
    found = _objects(root, base, href, markup)
    owners = {id(item.root): item for item in found}

    items: list[tuple[int, int, ParsedItem]] = [
        (order[id(item.root)], 0, item.parsed) for item in found
    ]

    for index, element in enumerate(find_blocks(soup)):
        place = dict(base)
        place["block"] = index

        # Уровень заголовка — из самого тега. По нему предлагаются границы
        # глав (глава — заголовок верхнего уровня, а не каждый подзаголовок)
        # и по нему же сборка выгрузки ставит заголовку его уровень.
        level = HEADING_LEVELS.get(element.name)
        if level is not None:
            place["level"] = level

        links = _links(element, href)
        if links:
            place["links"] = links

        block = ParsedBlock(
            text=block_text(element), kind=BLOCK_KINDS[element.name], location=place
        )
        owner = _owner(element, owners)

        if owner is not None:
            caption = element.name in CAPTION_TAGS and element.parent in owner.caption_parents
            block.owner = Owner(object=owner.parsed, caption=caption)
            cell = owner.cell_of(element)
            if cell is not None:
                place["row"], place["column"] = cell

        # Ноль у объекта и единица у блока: листинг — сам себе блок, и
        # объект обязан встать раньше своего содержимого.
        items.append((order[id(element)], 1, block))

    stream = [item for _, _, item in sorted(items, key=lambda entry: (entry[0], entry[1]))]
    bind_captions(stream)

    yield from stream


@dataclass(frozen=True, slots=True)
class _Found:
    """Объект, найденный в разметке, и то, как узнать его блоки."""

    # Элемент, внутри которого всё — объект: `<figure>`, `<table>`, `<pre>`.
    root: Tag
    parsed: ParsedObject
    # Родители, прямой ребёнок-подпись которых — подпись объекта:
    # `<figure>` для `<figcaption>`, `<table>` для `<caption>`.
    caption_parents: tuple[Tag, ...] = ()
    # Ячейки таблицы и их места в сетке.
    cells: dict[int, tuple[int, int]] = field(default_factory=dict)

    def cell_of(self, element: Tag) -> tuple[int, int] | None:
        """Строка и столбец ячейки, в которой стоит блок."""
        for node in (element, *element.parents):
            if id(node) in self.cells:
                return self.cells[id(node)]
            if node is self.root:
                break

        return None


def _owner(element: Tag, owners: dict[int, _Found]) -> _Found | None:
    """Ближайший объект, внутри которого стоит блок: таблица во вложенной таблице — своя."""
    for node in (element, *element.parents):
        if id(node) in owners:
            return owners[id(node)]

    return None


def _objects(root: Tag, base: dict[str, Any], href: str | None, markup: str) -> list[_Found]:
    """Объекты разметки в порядке документа.

    Всё внутри `<figure>`, листинга, формулы и рисунка SVG принадлежит им и
    отдельными объектами не становится: картинка в листинге — часть
    листинга. Таблица — исключение: рисунок в её ячейке и вложенная
    таблица остаются самостоятельными объектами.
    """
    found: list[_Found] = []
    claimed: set[int] = set()

    for element in root.find_all(OBJECT_TAGS):
        if not isinstance(element, Tag) or id(element) in claimed or _under_ignored(element, root):
            continue

        made = _object(element, base, href, markup)
        if made is None:
            continue

        found.append(made)
        if element.name != "table":
            claimed.update(id(node) for node in element.descendants)

    return found


def _object(element: Tag, base: dict[str, Any], href: str | None, markup: str) -> _Found | None:
    if element.name == "figure":
        return _figure(element, base, href, markup)

    if element.name == "table":
        return _table(element, root=element, base=base, href=href)

    if element.name == "pre":
        return _code(element, root=element, base=base, href=href) if block_text(element) else None

    if element.name == "math":
        return (
            _equation(element, root=element, base=base, href=href) if _is_display(element) else None
        )

    images = _image_sources(element, href, markup)

    return _picture(element, images, base=base, href=href) if images else None


def _figure(figure: Tag, base: dict[str, Any], href: str | None, markup: str) -> _Found | None:
    """`<figure>` — обёртка: что в ней лежит, тем объектом она и становится.

    Таблица в обёртке — таблица с подписью из `<figcaption>`, листинг —
    листинг. Обёртка без таблицы, кода, формулы и изображений объектом не
    становится: так оформляют, например, эпиграфы.
    """
    table = figure.find("table")
    if isinstance(table, Tag):
        return _table(table, root=figure, base=base, href=href)

    pre = figure.find("pre")
    if isinstance(pre, Tag) and block_text(pre):
        return _code(pre, root=figure, base=base, href=href)

    math = figure.find("math")
    if isinstance(math, Tag):
        return _equation(math, root=figure, base=base, href=href)

    images = [
        source
        for picture in figure.find_all(["img", "svg"])
        if isinstance(picture, Tag) and picture.find_parent("svg") is None
        for source in _image_sources(picture, href, markup)
    ]

    return _picture(figure, images, base=base, href=href) if images else None


def _picture(
    root: Tag, images: list[ImageSource], *, base: dict[str, Any], href: str | None
) -> _Found:
    parsed = ParsedObject(
        type=ObjectType.FIGURE,
        location=_object_location(root, base),
        images=tuple(images),
        anchors=_anchors(root, href),
    )

    return _Found(root=root, parsed=parsed, caption_parents=(root,))


def _table(table: Tag, *, root: Tag, base: dict[str, Any], href: str | None) -> _Found:
    cells, grid = _grid(table)
    parsed = ParsedObject(
        type=ObjectType.TABLE,
        location=_object_location(root, base),
        payload=grid,
        anchors=_anchors(root, href),
    )

    return _Found(root=root, parsed=parsed, caption_parents=(root, table), cells=cells)


def _code(pre: Tag, *, root: Tag, base: dict[str, Any], href: str | None) -> _Found:
    parsed = ParsedObject(
        type=ObjectType.CODE,
        location=_object_location(root, base),
        payload={"language": _language(pre)},
        anchors=_anchors(root, href),
    )

    return _Found(root=root, parsed=parsed, caption_parents=(root,))


def _equation(math: Tag, *, root: Tag, base: dict[str, Any], href: str | None) -> _Found:
    parsed = ParsedObject(
        type=ObjectType.EQUATION,
        location=_object_location(root, base),
        payload=mathml_payload(math),
        label=_equation_number(math),
        anchors=_anchors(root, href),
    )

    return _Found(root=root, parsed=parsed, caption_parents=(root,))


def _is_display(math: Tag) -> bool:
    """Формула стоит отдельно, а не внутри фразы.

    Так её объявил автор (`display="block"`), или вокруг неё нет текста:
    абзац из одной формулы — выносная формула, как бы она ни была
    размечена.
    """
    if math.get("display") == "block":
        return True

    container = math.find_parent(BLOCK_TAGS)

    return container is None or is_formula_only(container)


def _equation_number(math: Tag) -> str | None:
    """Номер «(3.2)», стоящий в том же абзаце, что и единственная формула."""
    container = math.find_parent(BLOCK_TAGS)

    if container is None or len(container.find_all("math")) != 1:
        return None

    outside = "".join(
        str(node)
        for node in container.strings
        if not any(parent.name == "math" for parent in _parents_within(node, container))
    )
    match = EQUATION_NUMBER.match(outside)

    return normalize_number(match.group("number")) if match is not None else None


def _grid(table: Tag) -> tuple[dict[int, tuple[int, int]], dict[str, Any]]:
    """Сетка таблицы по правилам HTML: объединения по строкам и столбцам.

    Ячейка встаёт в первый свободный столбец своей строки — свободный от
    ячеек выше, растянутых вниз. Вложенная таблица сюда не попадает: у неё
    своя сетка.
    """
    taken: set[tuple[int, int]] = set()
    places: dict[int, tuple[int, int]] = {}
    cells: list[dict[str, Any]] = []
    rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
    height = 0
    width = 0

    for row_no, row in enumerate(rows):
        column = 0
        header_row = row.find_parent("thead") is not None and row.find_parent("table") is table

        for cell in row.find_all(["td", "th"], recursive=False):
            while (row_no, column) in taken:
                column += 1

            rowspan = _span(cell.get("rowspan"))
            colspan = _span(cell.get("colspan"))

            taken.update(
                (row_no + down, column + right)
                for down in range(rowspan)
                for right in range(colspan)
            )
            places[id(cell)] = (row_no, column)
            cells.append(
                {
                    "row": row_no,
                    "col": column,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "header": cell.name == "th" or header_row,
                }
            )

            height = max(height, row_no + rowspan)
            width = max(width, column + colspan)
            column += colspan

    return places, {"rows": height, "cols": width, "cells": cells}


def _span(value: object) -> int:
    """Объединение ячеек — целое от единицы до разумного предела.

    `rowspan="0"` по стандарту тянет ячейку до конца раздела; в книгах так
    не размечают, и такая ячейка считается одиночной. Предел защищает от
    `colspan="100000"`, который иначе развернулся бы в миллионы клеток.
    """
    text = str(value).strip() if value is not None else ""

    return min(int(text), MAX_SPAN) if text.isdigit() and int(text) > 0 else 1


def _language(pre: Tag) -> str | None:
    """Язык листинга из классов `language-python` / `lang-python` у `<pre>` или `<code>`."""
    code = pre.find("code")
    holders = [pre, code] if isinstance(code, Tag) else [pre]

    for holder in holders:
        for name in (_attribute(holder, "class") or "").split():
            match = _LANGUAGE.match(name)
            if match is not None:
                return match.group(1).lower()

    return None


def _image_sources(element: Tag, href: str | None, markup: str) -> list[ImageSource]:
    """Изображения элемента: файл в архиве, вложенные данные или сама разметка SVG."""
    if element.name == "img":
        src = _attribute(element, "src")
        return [_image(src, href, alt=_attribute(element, "alt"))] if src else []

    if element.name != "svg":
        return []

    # Обложки EPUB часто — SVG-обёртка вокруг одного растрового файла.
    # Тогда рисунок — этот файл, а не обёртка.
    references = [
        reference
        for image in element.find_all("image")
        if isinstance(image, Tag)
        and (reference := _attribute(image, "xlink:href") or _attribute(image, "href"))
    ]
    if references:
        return [_image(reference, href, alt=None) for reference in references]

    return [ImageSource(data=_source_of(element, markup).encode())]


def _image(src: str, href: str | None, *, alt: str | None) -> ImageSource:
    data = _data_uri(src)

    if data is not None:
        return ImageSource(data=data, alt=alt)

    return ImageSource(member=_member(href, src), src=src, alt=alt)


def _member(href: str | None, src: str) -> str | None:
    """Путь изображения внутри архива EPUB — от файла главы, где оно стоит.

    У отдельного HTML архива нет: изображение лежит где-то рядом с файлом,
    и в загруженном документе его нет.
    """
    parts = urlsplit(src)

    if href is None or parts.scheme or parts.netloc or not parts.path:
        return None

    return posixpath.normpath(posixpath.join(posixpath.dirname(href), unquote(parts.path)))


def _data_uri(src: str) -> bytes | None:
    """Байты из `data:image/png;base64,…` — изображение прямо в разметке."""
    header, separator, body = src.partition(",")

    if not separator or not header.lower().startswith("data:") or ";base64" not in header.lower():
        return None

    try:
        return base64.b64decode(body, validate=True)
    except binascii.Error:
        return None


def _source_of(element: Tag, markup: str) -> str:
    """Разметка элемента ровно так, как она записана в файле.

    Разбор HTML переводит имена атрибутов в нижний регистр, и SVG с
    `viewbox` вместо `viewBox` рисуется не в том масштабе. Оригинал
    рисунка обязан остаться оригиналом, поэтому берётся кусок исходного
    текста: от открывающего тега до парного закрывающего.
    """
    if element.sourceline is None or element.sourcepos is None:
        return str(element)

    # Строки — по переводу строки, как их считает сам `html.parser`.
    lines = markup.split("\n")
    start = sum(len(line) + 1 for line in lines[: element.sourceline - 1]) + element.sourcepos
    depth = 0

    for match in _SVG_TAG.finditer(markup, start):
        if match.group("self"):
            if depth == 0:
                return markup[start : match.end()]
            continue

        depth += -1 if match.group("close") else 1

        if depth == 0:
            return markup[start : match.end()]

    return str(element)


def _object_location(root: Tag, base: dict[str, Any]) -> dict[str, Any]:
    place = dict(base)
    place["tag"] = root.name

    identifier = _attribute(root, "id")
    if identifier:
        place["id"] = identifier

    return place


def _anchors(root: Tag, href: str | None) -> tuple[str, ...]:
    """Якоря объекта — `id` его самого и всего внутри: ссылаются и на `<img id>`."""
    identifiers = [_attribute(root, "id")] + [
        _attribute(node, "id") for node in root.find_all(id=True) if isinstance(node, Tag)
    ]

    return tuple(f"{href or ''}#{value}" for value in identifiers if value)


def _links(element: Tag, href: str | None) -> list[str]:
    """Куда ведут ссылки блока — в тех же координатах, что и якоря объектов."""
    targets = (
        _target(href, _attribute(link, "href") or "")
        for link in element.find_all("a", href=True)
        if isinstance(link, Tag)
    )

    return [target for target in targets if target is not None]


def _target(href: str | None, link: str) -> str | None:
    """Ссылка внутрь книги: `#fig3` или `ch03.xhtml#fig3`. Внешние не нужны."""
    parts = urlsplit(link)

    if parts.scheme or parts.netloc or not parts.fragment:
        return None

    if not parts.path:
        return f"{href or ''}#{parts.fragment}"

    path = unquote(parts.path)
    if href is not None:
        path = posixpath.normpath(posixpath.join(posixpath.dirname(href), path))

    return f"{path}#{parts.fragment}"


def _attribute(element: Tag, name: str) -> str | None:
    value = element.get(name)

    if value is None:
        return None

    return " ".join(value) if isinstance(value, list) else str(value)


class HtmlParser:
    def parse(self, path: Path) -> Iterator[ParsedItem]:
        yield from blocks_from_html(read_text(path))


class EpubParser:
    def parse(self, path: Path) -> Iterator[ParsedItem]:
        try:
            with zipfile.ZipFile(path) as archive:
                # Оглавление проверяется до первого чтения: пятьдесят
                # мегабайт по правилам загрузки разворачиваются в десятки
                # гигабайт, и узнавать об этом по памяти процесса поздно.
                check_archive(archive)

                for order, name in enumerate(_spine(archive)):
                    try:
                        markup = read_member(archive, name).decode("utf-8", errors="replace")
                    except KeyError:
                        # Опись ссылается на файл, которого в архиве нет.
                        # Пропускаем главу, но книгу не роняем: остальные
                        # главы перевести всё ещё можно.
                        continue

                    yield from blocks_from_html(markup, {"chapter": order, "href": name})
        except zipfile.BadZipFile as error:
            raise ParsingError("Файл не читается как EPUB: повреждён архив") from error
        except ArchiveTooLargeError as error:
            raise ParsingError(str(error)) from error


def read_opf(archive: zipfile.ZipFile) -> tuple[Element, str]:
    """Опись EPUB и каталог, от которого считаются пути внутри неё.

    Путь до описи берётся из `META-INF/container.xml` — он не обязан быть
    `OEBPS/content.opf`, и у части издателей он другой.

    Вынесено из разбора глав, потому что по той же описи читаются название
    и автор при проверке исходника. Два отдельных чтения одного файла
    однажды разошлись бы в обработке ошибок, и половина EPUB читалась бы
    строже другой.
    """
    try:
        container = ElementTree.fromstring(read_member(archive, "META-INF/container.xml"))
    except (KeyError, ElementTree.ParseError, DefusedXmlException) as error:
        # DefusedXmlException — это отбитая попытка развернуть сущности или
        # утянуть внешний файл. Для читающего это просто «опись не читается»:
        # подробности ему не помогут, а нападающему подскажут.
        raise ParsingError("EPUB без META-INF/container.xml") from error

    rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    opf_path = rootfile.get("full-path") if rootfile is not None else None
    if not opf_path:
        raise ParsingError("В EPUB не указан путь к описи (rootfile)")

    try:
        opf = ElementTree.fromstring(read_member(archive, opf_path))
    except (KeyError, ElementTree.ParseError, DefusedXmlException) as error:
        raise ParsingError("Опись EPUB не читается") from error

    return opf, posixpath.dirname(opf_path)


def _spine(archive: zipfile.ZipFile) -> list[str]:
    """Пути к главам в порядке чтения."""
    opf, base = read_opf(archive)
    ns = {"opf": "http://www.idpf.org/2007/opf"}

    hrefs: dict[str, str] = {}
    for item in opf.findall("opf:manifest/opf:item", ns):
        item_id = item.get("id")
        href = item.get("href")
        if item_id and href:
            hrefs[item_id] = posixpath.normpath(posixpath.join(base, href)) if base else href

    order: list[str] = []
    for ref in opf.findall("opf:spine/opf:itemref", ns):
        # linear="no" — приложения и обложки, которые читатель не проходит
        # подряд. В переводе они нужны, поэтому берём и их.
        target = hrefs.get(ref.get("idref") or "")
        if target and target.lower().endswith(_XHTML_SUFFIXES):
            order.append(target)

    if not order:
        raise ParsingError("В описи EPUB нет ни одной главы")

    return order
