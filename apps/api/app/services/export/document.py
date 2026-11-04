"""Содержание выпуска как последовательность элементов.

Из него собираются и PDF, и новый DOCX: содержание одно, отличается только вёрстка. Весь текст
здесь уже взят из редакций манифеста, а рисунки — из разрешённого набора: другого источника у
сборщиков нет.
"""

from dataclasses import dataclass, field

from app.models.block import BlockKind

ASSET_SCHEME = "asset:"


@dataclass(frozen=True, slots=True)
class TextElement:
    block_id: str
    kind: BlockKind
    text: str
    level: int = 1


@dataclass(frozen=True, slots=True)
class TableCell:
    text: str
    rowspan: int = 1
    colspan: int = 1
    header: bool = False
    block_id: str | None = None


@dataclass(frozen=True, slots=True)
class TableElement:
    rows: list[list[TableCell]]


@dataclass(frozen=True, slots=True)
class FigureElement:
    # Адреса изображений из набора `images`, пропавшие в исходнике сюда не попадают.
    urls: list[str]
    alts: list[str]


@dataclass(frozen=True, slots=True)
class FormulaElement:
    text: str


@dataclass(frozen=True, slots=True)
class TocEntry:
    level: int
    text: str
    block_id: str


Element = TextElement | TableElement | FigureElement | FormulaElement


@dataclass(slots=True)
class PublicationDocument:
    title: str
    language: str
    elements: list[Element] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    # Адрес → (байты, тип). Других источников у сборщиков нет.
    images: dict[str, tuple[bytes, str]] = field(default_factory=dict)


def asset_url(index: int) -> str:
    return f"{ASSET_SCHEME}{index}"
