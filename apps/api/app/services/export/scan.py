"""Проверка готового файла: в читательской версии нет служебного.

Смотрит не на блоки, а на файл, который уйдёт читателю: служебное может прийти и не из текста, а из
исходника, колонтитула или оглавления. Коды блоков, замечаний и объектов, заменители и заметки
проверяющих живут в базе, в файле их быть не должно.

Строка, которая есть в самом исходнике, служебной не считается: номер детали в книге может
выглядеть как код блока, и запрещать его значило бы никогда не выпустить эту книгу. Заметка
считается совпадением только целой длинной фразой: короткая заметка («Радиус») совпадёт с обычным
текстом, а отказ здесь останавливает выпуск."""

import io
import re
import zipfile
from collections.abc import Iterable, Sequence

from bs4 import BeautifulSoup
from defusedxml import ElementTree

from app.services.export.base import ExportError, Rendered

# Служебные коды. Границы слова обязательны: иначе совпадёт и кусок обычной строки.
_MARKERS = (
    ("код замечания", re.compile(r"\bBK\d{2,}-CH\d{2,}-ERR-\d{2,}\b")),
    ("код замечания", re.compile(r"\bERR-\d{4,}\b")),
    ("код выпуска", re.compile(r"\bBK\d{2,}-(?:CH\d{2,}-FINAL|RELEASE)-v\d+\.\d+\b")),
    ("код блока", re.compile(r"\bCH\d{2,}-B\d{4,}\b")),
    ("код объекта", re.compile(r"\bCH\d{2,}-(?:FIG|TBL|EQ|CODE)\d{3,}\b")),
    ("код главы и книги", re.compile(r"\bBK\d{2,}-CH\d{2,}\b")),
)
_PLACEHOLDER = re.compile(r"⟦\d*⟧?")

NOTE_MIN_LENGTH = 40

# Сколько распакованного готовы прочитать из одной части. Файл собран из чужого исходника.
_PART_MAX = 64 * 1024 * 1024

_WORD_PARTS = re.compile(
    r"^word/(document|header\d*|footer\d*|footnotes|endnotes|comments\w*)\.xml$"
)
_MARKUP_PARTS = re.compile(r"\.(x?html?|ncx)$", re.IGNORECASE)


def readable_text(rendered: Rendered) -> str:
    """Весь текст файла, который увидит читатель."""
    if rendered.suffix == ".docx":
        return _text_of_zip(rendered.content, _WORD_PARTS, _xml_text)
    if rendered.suffix == ".epub":
        return _text_of_zip(rendered.content, _MARKUP_PARTS, _markup_text)
    if rendered.suffix in (".html", ".htm", ".xhtml"):
        return _markup_text(rendered.content)

    return rendered.content.decode("utf-8", errors="replace")


def scan(
    text: str,
    *,
    source_texts: Iterable[str] = (),
    notes: Sequence[str] = (),
) -> list[str]:
    """Что служебного нашлось. Пустой список означает чистый файл."""
    from_source = "\n".join(source_texts)
    found: list[str] = []

    for name, pattern in _MARKERS:
        for match in sorted(set(pattern.findall(text))):
            if match not in from_source:
                found.append(f"{name} {match}")

    if _PLACEHOLDER.search(text):
        found.append("заменитель объекта")

    for note in notes:
        clean = note.strip()
        if len(clean) >= NOTE_MIN_LENGTH and clean in text and clean not in from_source:
            found.append(f"заметка проверяющего: {clean[:60]}…")

    return found


def _text_of_zip(content: bytes, wanted: re.Pattern[str], read: object) -> str:
    assert callable(read)

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise ExportError("Готовый файл не читается для проверки") from error

    parts: list[str] = []

    with archive:
        for info in archive.infolist():
            if not wanted.search(info.filename):
                continue
            if info.file_size > _PART_MAX:
                raise ExportError(f"Часть файла {info.filename} слишком велика для проверки")

            parts.append(read(archive.read(info)))

    return "\n".join(parts)


def _xml_text(content: bytes) -> str:
    # Куски одного слова лежат в разных узлах, поэтому склеиваем без разделителя: код, разорванный
    # на два фрагмента, тоже код.
    return "".join(ElementTree.fromstring(content).itertext())


def _markup_text(content: bytes) -> str:
    return BeautifulSoup(content, "html.parser").get_text()
