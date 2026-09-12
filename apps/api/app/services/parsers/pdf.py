"""PDF с текстовым слоем.

PDF — не разметка, а описание того, где какая буква нарисована. Абзацев,
заголовков и списков в нём нет: есть буквы с координатами, и всё остальное
приходится восстанавливать. Восстановление делает pdfminer — он собирает
буквы в строки, строки в блоки по расстоянию между ними, — а здесь
решается то, чего библиотека знать не может: что из блоков колонтитул, где
заголовок, где перенос слова, а где пункт списка.

Правила намеренно простые и перечислены явно. Каждое ошибается на какой-то
книге, и когда ошибётся — его можно найти и поправить, а не искать причину в
обученной модели.

Сканы сюда не относятся: у скана текстового слоя нет, и разбор честно
отвечает, что это скан. Распознавание — отдельная работа, и делать её
вид, что «текст не нашёлся», нельзя: человек пойдёт чинить файл, который
исправен.
"""

import re
import statistics
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import (
    LAParams,
    LTChar,
    LTFigure,
    LTImage,
    LTTextContainer,
    LTTextLineHorizontal,
)
from pdfminer.pdftypes import PDFException
from pdfminer.psparser import PSException

from app.core.config import get_settings
from app.models.segment import SegmentKind
from app.services.parsers.base import ParsedBlock, ParsingError

# Насколько крупнее основного текста должен быть блок, чтобы считаться
# заголовком. Полтора кегля — заметная разница; на десятой доле заголовком
# оказывалась бы каждая строка чуть крупнее соседней.
HEADING_SIZE_RATIO = 1.2
HEADING_MAX_CHARS = 160
HEADING_MAX_LINES = 3

# Колонтитул — то, что повторяется страница за страницей. Три страницы —
# нижний порог: две совпавшие строки бывают и в тексте.
REPEATED_MIN_PAGES = 3

_BULLET = re.compile(r"^\s*(?:[•·▪○◦■\-–—*]|\d{1,3}[.)]|[a-zа-я][.)])\s+(?=\S)")
_PAGE_NUMBER = re.compile(
    r"^\s*(?:page|стр\.?|с\.|p\.)?\s*\d{1,4}\s*(?:(?:of|/|из)\s*\d{1,4})?\s*$", re.IGNORECASE
)
_WARNING = re.compile(r"^\s*(?:warning|caution|danger|внимание|осторожно|опасно)\b", re.IGNORECASE)
_CAPTION = re.compile(
    r"^\s*(?:fig\.?|figure|рис\.?|рисунок|table|таблица|табл\.)\s*\d", re.IGNORECASE
)
_DIGITS = re.compile(r"\d+")
_ALNUM = re.compile(r"[^\W_]", re.UNICODE)


@dataclass(slots=True)
class _Box:
    """Блок текста, как его собрал pdfminer: строки и кегль."""

    page: int
    lines: list[str]
    size: float
    characters: int

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(slots=True)
class _Pages:
    boxes: list[_Box] = field(default_factory=list)
    total: int = 0
    # Страницы без текста, но с картинкой: так выглядит скан.
    image_only: int = 0


class PdfParser:
    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        pages = _read(path)

        if not pages.boxes:
            if pages.image_only:
                raise ParsingError(
                    f"В PDF нет текстового слоя: это скан, {pages.image_only} "
                    f"{_pages_word(pages.image_only)} с картинками. Распознавание "
                    "сканов пока не делается — пришлите текстовый PDF или DOCX."
                )

            raise ParsingError("В PDF не нашлось текста")

        body_size = _body_size(pages.boxes)
        repeated = _repeated_lines(pages.boxes, pages.total)

        pieces = (
            (text, kind, box.page)
            for box in pages.boxes
            if not _is_furniture(box, repeated)
            for text, kind in _blocks_of(box, body_size)
        )

        for index, (text, kind, page) in enumerate(_merged(pieces)):
            yield ParsedBlock(text=text, kind=kind, location={"page": page, "block": index})


def _read(path: Path) -> _Pages:
    """Собрать блоки всех страниц.

    Блоки собираются целиком до выдачи: колонтитул виден только по повтору
    на других страницах, а кегль основного текста — только по всей книге.
    Держится при этом текст, а не разметка pdfminer — книга на тысячу
    страниц в память помещается.
    """
    limit = get_settings().pdf_max_pages
    pages = _Pages()
    laparams = LAParams(detect_vertical=False)

    try:
        # На одну больше предела: так видно, что предел превышен, без
        # разбора всей книги.
        for number, page in enumerate(
            extract_pages(str(path), laparams=laparams, maxpages=limit + 1), start=1
        ):
            if number > limit:
                raise ParsingError(
                    f"В PDF больше {limit} страниц. Разделите файл на части: "
                    "разбор идёт в запросе, и тысяча страниц в нём не помещается."
                )

            pages.total = number
            has_image = False
            has_text = False

            for element in page:
                if isinstance(element, LTFigure | LTImage):
                    has_image = True
                    continue

                if not isinstance(element, LTTextContainer):
                    continue

                box = _box_of(element, number)
                if box is not None:
                    pages.boxes.append(box)
                    has_text = True

            if has_image and not has_text:
                pages.image_only += 1
    except ParsingError:
        raise
    except (PSException, PDFException) as error:
        raise ParsingError(f"Файл не читается как PDF: {_reason(error)}") from error

    return pages


def _reason(error: Exception) -> str:
    name = type(error).__name__

    if "Password" in name:
        return "документ защищён паролем"

    return str(error) or name


def _box_of(element: LTTextContainer[Any], page: int) -> _Box | None:
    lines: list[str] = []
    sizes: list[float] = []

    for line in element:
        if not isinstance(line, LTTextLineHorizontal):
            continue

        text = line.get_text().strip()
        if not text:
            continue

        lines.append(text)
        sizes.extend(char.size for char in line if isinstance(char, LTChar))

    if not lines or not sizes:
        return None

    return _Box(
        page=page,
        lines=lines,
        size=statistics.median(sizes),
        characters=sum(len(line) for line in lines),
    )


def _body_size(boxes: list[_Box]) -> float:
    """Кегль основного текста — тот, которым набрано больше всего знаков."""
    weight: Counter[float] = Counter()

    for box in boxes:
        weight[round(box.size, 1)] += box.characters

    return weight.most_common(1)[0][0]


def _normalize(text: str) -> str:
    """Вид строки для сравнения между страницами: числа не в счёт.

    «Глава 3 · 17» и «Глава 3 · 18» — один и тот же колонтитул с разным
    номером страницы.
    """
    return _DIGITS.sub("#", " ".join(text.split())).casefold()


def _repeated_lines(boxes: list[_Box], total_pages: int) -> set[str]:
    """Строки, повторяющиеся на многих страницах, — колонтитулы."""
    if total_pages < REPEATED_MIN_PAGES:
        return set()

    seen: dict[str, set[int]] = {}

    for box in boxes:
        # Колонтитул — короткий блок; абзац из десяти строк повториться на
        # трёх страницах не может, а сравнивать его целиком дорого.
        if len(box.lines) > 2:
            continue

        key = _normalize(box.text)
        if key:
            seen.setdefault(key, set()).add(box.page)

    return {key for key, pages in seen.items() if len(pages) >= REPEATED_MIN_PAGES}


def _is_furniture(box: _Box, repeated: set[str]) -> bool:
    """Не текст книги: номер страницы, колонтитул, обрывок в один знак."""
    text = box.text

    if len(_ALNUM.findall(text)) < 2:
        return True

    if len(box.lines) <= 2 and _normalize(text) in repeated:
        return True

    return len(box.lines) == 1 and _PAGE_NUMBER.match(text) is not None


def _blocks_of(box: _Box, body_size: float) -> Iterator[tuple[str, SegmentKind]]:
    """Блок pdfminer — в один или несколько блоков книги.

    Список pdfminer собирает в один блок: пункты стоят строка под строкой
    на одном расстоянии. Здесь они разделяются по маркерам — каждый пункт
    переводится отдельно и сам по себе.
    """
    if _looks_like_list(box.lines):
        for item in _split_items(box.lines):
            yield item, SegmentKind.LIST_ITEM
        return

    text = _join(box.lines)

    yield text, _kind_of(box, text, body_size)


def _looks_like_list(lines: list[str]) -> bool:
    marked = sum(1 for line in lines if _BULLET.match(line))

    # Один маркер в начале — нумерованный заголовок или абзац «1. …»;
    # список — это когда маркеров хотя бы два.
    return marked >= 2 and _BULLET.match(lines[0]) is not None


def _split_items(lines: list[str]) -> list[str]:
    items: list[list[str]] = []

    for line in lines:
        if _BULLET.match(line) or not items:
            items.append([_BULLET.sub("", line, count=1)])
        else:
            items[-1].append(line)

    return [_join(item) for item in items if _join(item)]


def _merged(
    pieces: Iterator[tuple[str, SegmentKind, int]],
) -> Iterator[tuple[str, SegmentKind, int]]:
    """Склеить абзац, который pdfminer отдал построчно.

    В плотно свёрстанных каталогах межстрочный просвет больше половины
    строки, и pdfminer видит в каждой строке отдельный блок. Строки одного
    абзаца узнаются по обрыву: предыдущая не кончается точкой, а следующая
    начинается со строчной, либо предыдущая оборвана на дефисе или запятой.
    Склейка только внутри страницы: абзац, перетёкший на следующую, —
    редкость, а склеивание через колонтитул — ошибка.
    """
    pending: tuple[str, SegmentKind, int] | None = None

    for text, kind, page in pieces:
        if (
            pending is not None
            and kind is SegmentKind.PARAGRAPH
            and pending[1] is SegmentKind.PARAGRAPH
            and pending[2] == page
            and _continues(pending[0], text)
        ):
            pending = (_join([pending[0], text]), kind, page)
            continue

        if pending is not None:
            yield pending

        pending = (text, kind, page)

    if pending is not None:
        yield pending


_SENTENCE_END = (".", "!", "?", ":", ";", "»", "”", '"', ")")


def _continues(previous: str, current: str) -> bool:
    if previous.endswith(_SENTENCE_END):
        return False

    return current[:1].islower() or previous.endswith(("-", ","))


def _join(lines: list[str]) -> str:
    """Строки блока — в один абзац.

    Перенос слова снимается, когда строка кончается дефисом, а следующая
    начинается со строчной: «sup-» + «ply» — это «supply». Дефис перед
    заглавной остаётся: «Ho-» + «Stoll» — это фамилия через дефис.
    """
    text = ""

    for line in lines:
        piece = " ".join(line.split())
        if not piece:
            continue

        if not text:
            text = piece
        elif text.endswith("-") and piece[:1].islower():
            text = text[:-1] + piece
        else:
            text = text + " " + piece

    return text


def _kind_of(box: _Box, text: str, body_size: float) -> SegmentKind:
    if _WARNING.match(text):
        return SegmentKind.WARNING

    if _CAPTION.match(text):
        return SegmentKind.CAPTION

    letters = [char for char in text if char.isalpha()]
    digits = sum(1 for char in text if char.isdigit())

    # Заголовок — это слова: телефон или артикул крупным кеглем на обложке
    # заголовком не становится.
    wordy = len(letters) >= 3 and len(letters) >= digits
    short = len(text) <= HEADING_MAX_CHARS and len(box.lines) <= HEADING_MAX_LINES

    if wordy and short and box.size >= body_size * HEADING_SIZE_RATIO:
        return SegmentKind.HEADING

    # Строка прописными — заголовок и в основном кегле: «ТЕХНИЧЕСКИЕ
    # ХАРАКТЕРИСТИКИ». Аббревиатура из трёх букв в счёт не идёт.
    if (
        wordy
        and short
        and len(box.lines) == 1
        and len(letters) >= 4
        and all(c.isupper() for c in letters)
    ):
        return SegmentKind.HEADING

    return SegmentKind.PARAGRAPH


def _pages_word(count: int) -> str:
    last, teen = count % 10, 11 <= count % 100 <= 14

    if teen or last == 0 or last >= 5:
        return "страниц"

    return "страница" if last == 1 else "страницы"
