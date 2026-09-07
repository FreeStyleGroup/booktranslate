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
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from app.models.segment import SegmentKind
from app.services.parsers.base import ParsedBlock, ParsingError
from app.services.parsers.plain import read_text

# Теги, дающие отдельный блок. Всё, что не перечислено (span, em, a),
# остаётся внутри блока — это оформление внутри предложения, а не граница.
_BLOCK_KINDS = {
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
_IGNORED = {"script", "style", "head", "title", "meta", "link", "noscript"}

_XHTML_SUFFIXES = (".xhtml", ".html", ".htm")


def blocks_from_html(
    markup: str, location: dict[str, object] | None = None
) -> Iterator[ParsedBlock]:
    """Разобрать разметку в блоки.

    Используется штатный `html.parser`: он всегда есть в поставке Python и не
    требует бинарной сборки. Битую разметку он чинит менее охотно, чем lxml,
    но в книгах она в основном валидная.
    """
    soup = BeautifulSoup(markup, "html.parser")

    for tag in soup.find_all(_IGNORED):
        tag.decompose()

    root = soup.body or soup
    index = 0

    for element in root.find_all(list(_BLOCK_KINDS)):
        if not isinstance(element, Tag):
            continue

        # Вложенный блок отдаётся сам по себе; родитель, который его
        # содержит, не должен выдать его текст второй раз.
        if element.find(list(_BLOCK_KINDS)) is not None:
            continue

        text = element.get_text(" ", strip=True)
        if not text:
            continue

        place = dict(location or {})
        place["block"] = index
        index += 1

        yield ParsedBlock(text=text, kind=_BLOCK_KINDS[element.name], location=place)


class HtmlParser:
    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        yield from blocks_from_html(read_text(path))


class EpubParser:
    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        try:
            with zipfile.ZipFile(path) as archive:
                for order, name in enumerate(_spine(archive)):
                    try:
                        markup = archive.read(name).decode("utf-8", errors="replace")
                    except KeyError:
                        # Опись ссылается на файл, которого в архиве нет.
                        # Пропускаем главу, но книгу не роняем: остальные
                        # главы перевести всё ещё можно.
                        continue

                    yield from blocks_from_html(markup, {"chapter": order, "href": name})
        except zipfile.BadZipFile as error:
            raise ParsingError("Файл не читается как EPUB: повреждён архив") from error


def _spine(archive: zipfile.ZipFile) -> list[str]:
    """Пути к главам в порядке чтения.

    Путь до описи берётся из `META-INF/container.xml` — он не обязан быть
    `OEBPS/content.opf`, и у части издателей он другой.
    """
    try:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    except (KeyError, ElementTree.ParseError) as error:
        raise ParsingError("EPUB без META-INF/container.xml") from error

    rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    opf_path = rootfile.get("full-path") if rootfile is not None else None
    if not opf_path:
        raise ParsingError("В EPUB не указан путь к описи (rootfile)")

    try:
        opf = ElementTree.fromstring(archive.read(opf_path))
    except (KeyError, ElementTree.ParseError) as error:
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
