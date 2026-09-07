"""Простой текст и Markdown.

Разделены не по формату файла, а по тому, что известно о разметке. В простом
тексте единственная надёжная граница — пустая строка: всё остальное было бы
гаданием. В Markdown разметка объявлена автором явно, и из неё видно, где
заголовок, где пункт списка, а где код, который переводить нельзя вовсе.
"""

import re
from collections.abc import Iterator
from pathlib import Path

from app.models.segment import SegmentKind
from app.services.parsers.base import ParsedBlock, ParsingError

# Кодировки в порядке убывания вероятности. UTF-8 сегодня почти всегда; CP1251
# встречается в старых выгрузках, а latin-1 принимает любой байт и потому
# стоит последним — он не столько распознаёт, сколько не даёт упасть.
_ENCODINGS = ("utf-8-sig", "cp1251", "latin-1")

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def read_text(path: Path) -> str:
    """Прочитать файл, подобрав кодировку.

    Кодировка не хранится: её никто не спрашивает при загрузке, а угадывание
    по содержимому даёт ошибку ровно там, где текст короткий.
    """
    data = path.read_bytes()

    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ParsingError("Не удалось определить кодировку файла")


class PlainTextParser:
    """Абзацы, разделённые пустой строкой."""

    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        text = read_text(path)

        for index, chunk in enumerate(re.split(r"\n\s*\n", text)):
            body = chunk.strip()
            if body:
                yield ParsedBlock(text=body, location={"block": index})


class MarkdownParser:
    """Заголовки, списки, код и абзацы.

    Блоки кода отдаются с типом CODE и дальше переводятся по своим правилам
    (а чаще не переводятся вовсе): перевод содержимого листинга ломает пример,
    ради которого он в книге и стоит.
    """

    def parse(self, path: Path) -> Iterator[ParsedBlock]:
        lines = read_text(path).splitlines()

        buffer: list[str] = []
        buffer_start = 0
        in_code = False
        code: list[str] = []
        code_start = 0

        def flush(kind: SegmentKind, body: list[str], line_no: int) -> ParsedBlock | None:
            text = "\n".join(body).strip()
            return ParsedBlock(text=text, kind=kind, location={"line": line_no}) if text else None

        for number, line in enumerate(lines, start=1):
            if _FENCE.match(line):
                if in_code:
                    block = flush(SegmentKind.CODE, code, code_start)
                    if block is not None:
                        yield block
                    code = []
                    in_code = False
                else:
                    block = flush(SegmentKind.PARAGRAPH, buffer, buffer_start)
                    if block is not None:
                        yield block
                    buffer = []
                    in_code = True
                    code_start = number
                continue

            if in_code:
                code.append(line)
                continue

            heading = _HEADING.match(line)
            item = None if heading else _LIST_ITEM.match(line)

            # Заголовок и пункт списка — сами по себе блок: они не
            # продолжают предыдущий абзац и не сливаются со следующим.
            if heading or item or not line.strip():
                block = flush(SegmentKind.PARAGRAPH, buffer, buffer_start)
                if block is not None:
                    yield block
                buffer = []

                if heading:
                    yield ParsedBlock(
                        text=heading.group(2).strip(),
                        kind=SegmentKind.HEADING,
                        location={"line": number, "level": len(heading.group(1))},
                    )
                elif item:
                    yield ParsedBlock(
                        text=item.group(1).strip(),
                        kind=SegmentKind.LIST_ITEM,
                        location={"line": number},
                    )

                continue

            if not buffer:
                buffer_start = number

            buffer.append(line)

        # Незакрытая тройная кавычка в конце файла — обычное дело в черновике;
        # накопленное отдаём как код, а не теряем.
        block = flush(
            SegmentKind.CODE if in_code else SegmentKind.PARAGRAPH,
            code if in_code else buffer,
            code_start if in_code else buffer_start,
        )
        if block is not None:
            yield block
