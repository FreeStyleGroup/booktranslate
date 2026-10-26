"""Формулы: запись как есть, нормализованная сумма и дерево для показа.

У формулы три представления, и каждое нужно для своего.

**Запись** — разметка формулы так, как её прочёл разборщик: MathML из
EPUB, OMML из DOCX. Она хранится целиком, и по ней считается сумма объекта.

**Нормализованная сумма** — по дереву формулы без пробелов между тегами и
с упорядоченными атрибутами. Два файла, где одна и та же формула записана с
разными отступами, дают разные записи, но одну нормализованную сумму: по
ней сверяется, что формула в переводе осталась той же формулой.

**Дерево для показа** — только MathML и только разрешённые элементы и
атрибуты. Экран строит из него разметку сам, элемент за элементом, поэтому
ни скрипт, ни ссылка, ни обработчик события из чужого файла на страницу не
попадут: их просто нет в перечне.
"""

import hashlib
import json
from typing import Any

from bs4 import Tag
from bs4.element import NavigableString
from lxml import etree

# Элементы MathML Core и распространённые в книгах из MathML 3. Остальное
# — `annotation`, `maction`, `semantics` со служебным содержимым — для
# показа не нужно, а перечень разрешённого обязан быть закрытым.
_PREVIEW_TAGS = frozenset(
    {
        "math",
        "mi",
        "mn",
        "mo",
        "ms",
        "mtext",
        "mspace",
        "mrow",
        "mfrac",
        "msqrt",
        "mroot",
        "mstyle",
        "merror",
        "mpadded",
        "mphantom",
        "mfenced",
        "menclose",
        "msub",
        "msup",
        "msubsup",
        "munder",
        "mover",
        "munderover",
        "mmultiscripts",
        "mprescripts",
        "none",
        "mtable",
        "mtr",
        "mlabeledtr",
        "mtd",
    }
)

# Атрибуты, которые меняют вид формулы. Ни одного, который ведёт наружу
# (`href`, `src`) или исполняется (`on*`, `style` с выражениями).
_PREVIEW_ATTRIBUTES = frozenset(
    {
        "accent",
        "accentunder",
        "close",
        "columnalign",
        "columnspan",
        "depth",
        "display",
        "displaystyle",
        "fence",
        "form",
        "height",
        "largeop",
        "linethickness",
        "lspace",
        "mathvariant",
        "maxsize",
        "minsize",
        "movablelimits",
        "notation",
        "open",
        "rowalign",
        "rowspan",
        "rspace",
        "scriptlevel",
        "separator",
        "separators",
        "stretchy",
        "symmetric",
        "width",
    }
)

# У `semantics` показывается первый ребёнок — сама формула; остальные —
# её же запись в другой нотации.
_SEMANTICS = "semantics"

# Предел глубины дерева: формула глубже сотни уровней — не формула, а
# попытка уронить разбор рекурсией.
_MAX_DEPTH = 100

Tree = list[Any]


def mathml_payload(element: Tag) -> dict[str, Any]:
    """Всё, что хранится о формуле MathML."""
    return {
        "notation": "mathml",
        "raw": str(element),
        "text": element.get_text(" ", strip=True),
        "preview": preview_tree(element),
        "normalized": normalized_checksum(_canonical(element, depth=0)),
    }


def omml_payload(element: etree._Element) -> dict[str, Any]:
    """Всё, что хранится о формуле Word.

    Дерева для показа нет: OMML браузер не рисует, а перевод в MathML —
    отдельное преобразование со своими ошибками. Показывается текст
    формулы, запись хранится целиком.
    """
    return {
        "notation": "omml",
        "raw": etree.tostring(element, encoding="unicode"),
        "text": " ".join(part.strip() for part in element.itertext() if part.strip()),
        "preview": None,
        "normalized": normalized_checksum(_canonical_xml(element, depth=0)),
    }


def preview_tree(element: Tag) -> Tree | None:
    """Дерево MathML для показа: `[тег, {атрибуты}, ...дети]`, дети — деревья или текст."""
    return _preview(element, depth=0)


def normalized_checksum(tree: Tree | None) -> str:
    """Сумма по каноническому дереву: без пробелов между тегами, атрибуты по порядку."""
    payload = json.dumps(tree, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    return hashlib.sha256(payload.encode()).hexdigest()


def _preview(element: Tag, *, depth: int) -> Tree | None:
    if depth > _MAX_DEPTH:
        return None

    name = element.name.lower()

    if name == _SEMANTICS:
        first = next((child for child in element.children if isinstance(child, Tag)), None)
        return _preview(first, depth=depth + 1) if first is not None else None

    if name not in _PREVIEW_TAGS:
        return None

    attributes = {
        key.lower(): " ".join(value) if isinstance(value, list) else str(value)
        for key, value in element.attrs.items()
        if key.lower() in _PREVIEW_ATTRIBUTES
    }
    children: list[Any] = []

    for child in element.children:
        if isinstance(child, Tag):
            tree = _preview(child, depth=depth + 1)
            if tree is not None:
                children.append(tree)
        elif type(child) is NavigableString and child.strip():
            children.append(child.strip())

    return [name, attributes, *children]


def _canonical(element: Tag, *, depth: int) -> Tree | None:
    """Всё дерево целиком — для суммы, без отбора по перечню."""
    if depth > _MAX_DEPTH:
        return None

    attributes = {
        key.lower(): " ".join(value) if isinstance(value, list) else str(value)
        for key, value in element.attrs.items()
    }
    children: list[Any] = []

    for child in element.children:
        if isinstance(child, Tag):
            children.append(_canonical(child, depth=depth + 1))
        elif type(child) is NavigableString and child.strip():
            children.append(child.strip())

    return [element.name.lower(), attributes, *children]


def _canonical_xml(element: etree._Element, *, depth: int) -> Tree | None:
    """То же для разметки Word: текст узла и «хвосты» после детей — по порядку."""
    if depth > _MAX_DEPTH:
        return None

    children: list[Any] = []

    if element.text and element.text.strip():
        children.append(element.text.strip())

    for child in element:
        # Комментарии и инструкции обработки — не формула.
        if isinstance(child.tag, str):
            children.append(_canonical_xml(child, depth=depth + 1))
        if child.tail and child.tail.strip():
            children.append(child.tail.strip())

    return [
        str(element.tag),
        {str(key): str(value) for key, value in element.attrib.items()},
        *children,
    ]
