"""Чтение словарей из внешних источников.

Формат выбирается по расширению, а не по содержимому, — в отличие от
загружаемых документов, где расширение ничего не значит. Причина в том, что
CSV, TSV и текстовый список неотличимы по байтам, а ошибка здесь дешёвая:
файл словаря присылает тот же человек, который жмёт кнопку, и он видит
результат сразу.
"""

from pathlib import PurePosixPath

from app.services.dictionaries.base import (
    DictionaryContents,
    DictionaryError,
    ImportedTerm,
)
from app.services.dictionaries.registry import read_registry
from app.services.dictionaries.tabular import read_table
from app.services.dictionaries.tbx import read_tbx

__all__ = [
    "DictionaryContents",
    "DictionaryError",
    "ImportedTerm",
    "SUPPORTED_SUFFIXES",
    "read_dictionary",
]

SUPPORTED_SUFFIXES = (".csv", ".tsv", ".txt", ".tbx", ".xml", ".docx")


def read_dictionary(
    data: bytes, filename: str, *, source_language: str, target_language: str
) -> DictionaryContents:
    """Прочитать файл словаря.

    Языковая пара нужна только TBX: в нём одна запись несёт термин на
    десятке языков, и без указания пары непонятно, что с чем сопоставлять.
    В таблице и в реестре пара задаётся тем, куда их грузят.
    """
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.casefold()

    if suffix in (".csv", ".tsv", ".txt"):
        return read_table(data)

    if suffix in (".tbx", ".xml"):
        return read_tbx(data, source_language=source_language, target_language=target_language)

    if suffix == ".docx":
        return read_registry(data)

    raise DictionaryError(
        "Неизвестный формат словаря: " + (suffix or filename) + ". "
        "Поддерживаются " + ", ".join(SUPPORTED_SUFFIXES)
    )
