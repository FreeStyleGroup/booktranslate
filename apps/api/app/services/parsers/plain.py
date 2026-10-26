"""Простой текст и Markdown.

Разделены не по формату файла, а по тому, что известно о разметке. В простом
тексте единственная надёжная граница — пустая строка: всё остальное было бы
гаданием. В Markdown разметка объявлена автором явно, и из неё видно, где
заголовок, где пункт списка, а где код, который переводить нельзя вовсе.
"""

import re
from collections.abc import Iterator
from pathlib import Path

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.services.parsers.base import Owner, ParsedBlock, ParsedItem, ParsedObject, ParsingError

# Кодировки в порядке убывания вероятности. UTF-8 сегодня почти всегда; CP1251
# встречается в старых выгрузках, а latin-1 принимает любой байт и потому
# стоит последним — он не столько распознаёт, сколько не даёт упасть.
_ENCODINGS = ("utf-8-sig", "cp1251", "latin-1")

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)(.*)$")


def read_text(path: Path) -> str:
    """Прочитать файл, подобрав кодировку.

    Кодировка не хранится: её никто не спрашивает при загрузке, а угадывание
    по содержимому даёт ошибку ровно там, где текст короткий.
    """
    return decode_text(path.read_bytes())


def decode_text(data: bytes) -> str:
    """Разобрать байты как текст, подобрав кодировку.

    Отдельно от чтения файла: то же самое нужно загруженному словарю,
    который до диска не доходит.
    """
    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ParsingError("Не удалось определить кодировку файла")


class PlainTextParser:
    """Абзацы, разделённые пустой строкой."""

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        text = read_text(path)

        for index, chunk in enumerate(re.split(r"\n\s*\n", text)):
            body = chunk.strip()
            if body:
                yield ParsedBlock(text=body, location={"block": index})


class MarkdownParser:
    """Заголовки, списки, код и абзацы.

    Блок кода — листинг: объект с языком из строки открывающих кавычек
    (```python) и блок с его текстом. Дальше он переводится по своим правилам
    (а чаще не переводится вовсе): перевод содержимого листинга ломает пример,
    ради которого он в книге и стоит.
    """

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        lines = read_text(path).splitlines()

        buffer: list[str] = []
        buffer_start = 0
        in_code = False
        code: list[str] = []
        code_start = 0
        language: str | None = None

        def flush(kind: BlockKind, body: list[str], line_no: int) -> ParsedBlock | None:
            text = "\n".join(body).strip()
            return ParsedBlock(text=text, kind=kind, location={"line": line_no}) if text else None

        for number, line in enumerate(lines, start=1):
            fence = _FENCE.match(line)
            if fence:
                if in_code:
                    yield from _listing(code, code_start, language)
                    code = []
                    in_code = False
                else:
                    block = flush(BlockKind.PARAGRAPH, buffer, buffer_start)
                    if block is not None:
                        yield block
                    buffer = []
                    in_code = True
                    code_start = number
                    # Строка открытия — ```python: первое слово после
                    # кавычек — язык листинга.
                    words = fence.group(2).split()
                    language = words[0].lower() if words else None
                continue

            if in_code:
                code.append(line)
                continue

            heading = _HEADING.match(line)
            item = None if heading else _LIST_ITEM.match(line)

            # Заголовок и пункт списка — сами по себе блок: они не
            # продолжают предыдущий абзац и не сливаются со следующим.
            if heading or item or not line.strip():
                block = flush(BlockKind.PARAGRAPH, buffer, buffer_start)
                if block is not None:
                    yield block
                buffer = []

                if heading:
                    yield ParsedBlock(
                        text=heading.group(2).strip(),
                        kind=BlockKind.HEADING,
                        location={"line": number, "level": len(heading.group(1))},
                    )
                elif item:
                    yield ParsedBlock(
                        text=item.group(1).strip(),
                        kind=BlockKind.LIST_ITEM,
                        location={"line": number},
                    )

                continue

            if not buffer:
                buffer_start = number

            buffer.append(line)

        # Незакрытая тройная кавычка в конце файла — обычное дело в черновике;
        # накопленное отдаём как код, а не теряем.
        if in_code:
            yield from _listing(code, code_start, language)
            return

        block = flush(BlockKind.PARAGRAPH, buffer, buffer_start)
        if block is not None:
            yield block


def _listing(lines: list[str], line_no: int, language: str | None) -> Iterator[ParsedItem]:
    """Листинг — знак в знак.

    Отступ первой строки такой же текст, как остальное, и `strip()` срезал
    бы его. Отбрасываются только пустые строки по краям — они не в
    листинге, а вокруг него.
    """
    text = "\n".join(lines).strip("\n")

    if not text.strip():
        return

    listing = ParsedObject(
        type=ObjectType.CODE, location={"line": line_no}, payload={"language": language}
    )

    yield listing
    yield ParsedBlock(
        text=text, kind=BlockKind.CODE, location={"line": line_no}, owner=Owner(object=listing)
    )
