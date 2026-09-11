"""HTML и EPUB.

EPUB — это ZIP с набором XHTML-файлов и описью, в каком порядке их читать.
Поэтому оба формата разбираются одним кодом: EPUB добавляет к HTML только
распаковку и порядок глав.

Опись читается по-настоящему, а не подменяется сортировкой имён файлов:
в книгах главы сплошь и рядом называются `part0012.xhtml`, и алфавитный
порядок ставит одиннадцатую главу между первой и второй.
"""

import posixpath
import zipfile
from collections.abc import Iterator
from pathlib import Path

from bs4 import BeautifulSoup, CData, Tag

# NavigableString и PageElement пакет bs4 наружу не переэкспортирует —
# строгая типизация принимает их только из модуля, где они определены.
from bs4.element import NavigableString, PageElement

# Не штатный xml.etree: описи приходят из чужого файла, а штатный разбор
# разворачивает рекурсивно вложенные сущности («billion laughs») в гигабайты
# памяти. Термбазы разбираются так же (services/dictionaries/tbx.py).
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.models.segment import SegmentKind
from app.services.parsers.archives import ArchiveTooLargeError, check_archive, read_member
from app.services.parsers.base import ParsedBlock, ParsingError
from app.services.parsers.plain import read_text

# Теги, дающие отдельный блок. Всё, что не перечислено (span, em, a),
# остаётся внутри блока — это оформление внутри предложения, а не граница.
#
# Перечень открыт наружу намеренно: сборка переведённого документа обходит
# разметку тем же списком, и разойтись они не могут — иначе переводы встанут
# не в свои абзацы.
BLOCK_KINDS = {
    "h1": SegmentKind.HEADING,
    "h2": SegmentKind.HEADING,
    "h3": SegmentKind.HEADING,
    "h4": SegmentKind.HEADING,
    "h5": SegmentKind.HEADING,
    "h6": SegmentKind.HEADING,
    "p": SegmentKind.PARAGRAPH,
    "li": SegmentKind.LIST_ITEM,
    "td": SegmentKind.TABLE_CELL,
    "th": SegmentKind.TABLE_CELL,
    "figcaption": SegmentKind.CAPTION,
    "caption": SegmentKind.CAPTION,
    "blockquote": SegmentKind.PARAGRAPH,
    "pre": SegmentKind.CODE,
}

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

        blocks.append(element)

    return blocks


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
    ]


def block_text(element: Tag) -> str:
    """Текст блока: то же, что `get_text(" ", strip=True)`, но без служебных тегов."""
    parts = (str(node).strip() for node in block_strings(element))

    return " ".join(part for part in parts if part)


def _under_ignored(node: PageElement, stop: Tag) -> bool:
    """Стоит ли между узлом и `stop` служебный тег (сам `stop` не в счёт)."""
    for parent in node.parents:
        if parent is stop:
            return False

        if parent.name in IGNORED_TAGS:
            return True

    return False


def blocks_from_html(
    markup: str, location: dict[str, object] | None = None
) -> Iterator[ParsedBlock]:
    """Разобрать разметку в блоки.

    Используется штатный `html.parser`: он всегда есть в поставке Python и не
    требует бинарной сборки. Битую разметку он чинит менее охотно, чем lxml,
    но в книгах она в основном валидная.
    """
    soup = BeautifulSoup(markup, "html.parser")

    for index, element in enumerate(find_blocks(soup)):
        place = dict(location or {})
        place["block"] = index

        yield ParsedBlock(text=block_text(element), kind=BLOCK_KINDS[element.name], location=place)


class HtmlParser:
    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        yield from blocks_from_html(read_text(path))


class EpubParser:
    def parse(self, path: Path) -> Iterator[ParsedBlock]:
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


def _spine(archive: zipfile.ZipFile) -> list[str]:
    """Пути к главам в порядке чтения.

    Путь до описи берётся из `META-INF/container.xml` — он не обязан быть
    `OEBPS/content.opf`, и у части издателей он другой.
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

    ns = {"opf": "http://www.idpf.org/2007/opf"}
    base = posixpath.dirname(opf_path)

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
