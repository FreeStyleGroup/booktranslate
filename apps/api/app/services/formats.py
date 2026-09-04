"""Определение формата загруженного файла.

Расширению нельзя верить: его ставит человек, а от формата зависит, каким
разборщиком читать документ и что показать редактору. Поэтому решение
принимается по содержимому, а расширение служит подсказкой там, где по
содержимому не различить — текст, разметка Markdown и обычный txt выглядят
одинаково.

Файл к моменту проверки уже лежит на диске целиком, поэтому контейнеры
(DOCX, EPUB — это ZIP) читаются по-настоящему, через оглавление архива, а
не угадываются по первым байтам.
"""

import zipfile
from pathlib import Path

from app.models.document import SourceFormat

# Сколько байт хватает, чтобы узнать сигнатуру и заглянуть в начало текста.
_HEAD_BYTES = 8192

_SUFFIX_HINTS: dict[str, SourceFormat] = {
    ".md": SourceFormat.MARKDOWN,
    ".markdown": SourceFormat.MARKDOWN,
    ".html": SourceFormat.HTML,
    ".htm": SourceFormat.HTML,
    ".xliff": SourceFormat.XLIFF,
    ".xlf": SourceFormat.XLIFF,
    ".txt": SourceFormat.TXT,
    ".text": SourceFormat.TXT,
}

_MEDIA_TYPES: dict[SourceFormat, str] = {
    SourceFormat.PDF: "application/pdf",
    SourceFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    SourceFormat.EPUB: "application/epub+zip",
    SourceFormat.HTML: "text/html; charset=utf-8",
    SourceFormat.MARKDOWN: "text/markdown; charset=utf-8",
    SourceFormat.XLIFF: "application/xliff+xml",
    SourceFormat.TXT: "text/plain; charset=utf-8",
}

_EXTENSIONS: dict[SourceFormat, str] = {
    SourceFormat.PDF: ".pdf",
    SourceFormat.DOCX: ".docx",
    SourceFormat.EPUB: ".epub",
    SourceFormat.HTML: ".html",
    SourceFormat.MARKDOWN: ".md",
    SourceFormat.XLIFF: ".xlf",
    SourceFormat.TXT: ".txt",
}


def media_type(source_format: SourceFormat) -> str:
    """Тип содержимого для отдачи файла обратно."""
    return _MEDIA_TYPES[source_format]


def extension(source_format: SourceFormat) -> str:
    """Расширение для имени объекта в хранилище."""
    return _EXTENSIONS[source_format]


def _zip_format(path: Path) -> SourceFormat | None:
    """Что внутри ZIP-контейнера.

    DOCX опознаётся по обязательной части `word/document.xml`, EPUB — по
    первой записи `mimetype` со значением из спецификации. Проверять надо
    именно так: XLSX и PPTX — тоже ZIP с `[Content_Types].xml`, и по одному
    только признаку архива они прошли бы за документ Word.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())

            if "word/document.xml" in names:
                return SourceFormat.DOCX

            if "mimetype" in names:
                declared = archive.read("mimetype").strip()
                if declared == b"application/epub+zip":
                    return SourceFormat.EPUB
    except (zipfile.BadZipFile, KeyError, OSError):
        # Битый архив форматом не считается: разборщику его всё равно не
        # открыть, и лучше отказать на загрузке, чем через час разбора.
        return None

    return None


def _text_format(head: bytes, suffix: str) -> SourceFormat | None:
    """Формат текстового файла.

    Нулевой байт означает двоичное содержимое: ни один из поддерживаемых
    текстовых форматов его не содержит, а попытка показать такое редактору
    закончится мусором на экране.
    """
    if b"\x00" in head:
        return None

    try:
        # Хвост куска может обрезать многобайтный символ, поэтому ошибки
        # декодирования игнорируются: нам нужны только первые теги.
        sample = head.decode("utf-8", errors="ignore").lstrip().lower()
    except UnicodeDecodeError:  # pragma: no cover — errors="ignore" не бросает
        return None

    if "<xliff" in sample:
        return SourceFormat.XLIFF

    if sample.startswith("<!doctype html") or sample.startswith("<html") or "<body" in sample:
        return SourceFormat.HTML

    # Дальше по содержимому не различить: Markdown — это тот же текст, и
    # единственный источник намерения автора — расширение.
    return _SUFFIX_HINTS.get(suffix, SourceFormat.TXT)


def detect_format(path: Path, filename: str) -> SourceFormat | None:
    """Формат файла или None, если такой мы не принимаем."""
    with path.open("rb") as handle:
        head = handle.read(_HEAD_BYTES)

    if not head:
        return None

    if head.startswith(b"%PDF-"):
        return SourceFormat.PDF

    if head.startswith(b"PK\x03\x04"):
        return _zip_format(path)

    return _text_format(head, Path(filename).suffix.lower())
