"""CSV и TSV — то, в чём словарь приходит чаще всего.

Заказчик присылает глоссарий выгрузкой из таблицы, и предсказать в ней
нельзя ничего: разделитель бывает запятой, точкой с запятой (так выгружает
русский Excel) и табуляцией, кодировка — UTF-8 или CP1251, заголовок то
есть, то нет. Поэтому и разделитель, и наличие заголовка определяются по
содержимому, а не требуются от человека: требование «пришлите в правильном
формате» приводит к тому, что словарь не загрузят вовсе.
"""

import csv
import io

from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.services.dictionaries.base import DictionaryContents, DictionaryError, ImportedTerm
from app.services.parsers.plain import decode_text

# Имена колонок, которые встречаются в присылаемых выгрузках. Регистр и
# пробелы не в счёт.
_SOURCE_NAMES = frozenset(
    {"source", "source_term", "term", "en", "english", "термин", "исходник", "оригинал"}
)
_TARGET_NAMES = frozenset(
    {"target", "target_term", "translation", "ru", "russian", "перевод", "эквивалент"}
)
_NOTE_NAMES = frozenset({"note", "comment", "definition", "примечание", "комментарий", "описание"})
_KIND_NAMES = frozenset({"kind", "type", "разряд", "тип", "вид"})
_STATUS_NAMES = frozenset({"status", "статус", "состояние"})
_REFERENCE_NAMES = frozenset({"reference", "source_ref", "источник", "ссылка", "основание"})

# Значения колонки «разряд» в присылаемых словарях.
_KINDS = {
    "term": GlossaryEntryKind.TERM,
    "термин": GlossaryEntryKind.TERM,
    "abbreviation": GlossaryEntryKind.ABBREVIATION,
    "аббревиатура": GlossaryEntryKind.ABBREVIATION,
    "сокращение": GlossaryEntryKind.ABBREVIATION,
    "notation": GlossaryEntryKind.NOTATION,
    "обозначение": GlossaryEntryKind.NOTATION,
    "proper_name": GlossaryEntryKind.PROPER_NAME,
    "имя": GlossaryEntryKind.PROPER_NAME,
    "название": GlossaryEntryKind.PROPER_NAME,
    "do_not_translate": GlossaryEntryKind.DO_NOT_TRANSLATE,
    "непереводимое": GlossaryEntryKind.DO_NOT_TRANSLATE,
    "не переводить": GlossaryEntryKind.DO_NOT_TRANSLATE,
}

_STATUSES = {
    "proposed": GlossaryTermStatus.PROPOSED,
    "предложен": GlossaryTermStatus.PROPOSED,
    "confirmed": GlossaryTermStatus.CONFIRMED,
    "подтверждён": GlossaryTermStatus.CONFIRMED,
    "подтвержден": GlossaryTermStatus.CONFIRMED,
    "needs_review": GlossaryTermStatus.NEEDS_REVIEW,
    "требует перепроверки": GlossaryTermStatus.NEEDS_REVIEW,
    "needs_unification": GlossaryTermStatus.NEEDS_UNIFICATION,
    "требует унификации": GlossaryTermStatus.NEEDS_UNIFICATION,
    "retired": GlossaryTermStatus.RETIRED,
    "снят": GlossaryTermStatus.RETIRED,
}

_DELIMITERS = ",;\t|"
MAX_TERM_LENGTH = 300


def read_table(data: bytes) -> DictionaryContents:
    text = decode_text(data)

    if not text.strip():
        raise DictionaryError("Файл словаря пуст")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not rows:
        raise DictionaryError("В файле нет ни одной строки")

    columns = _columns(rows[0])
    contents = DictionaryContents()

    # Заголовок распознан — первая строка не данные. Если нет, читаем её как
    # обычную запись: словарь без заголовка это норма, а потерянная первая
    # строка обнаруживается не сразу.
    for row in rows[1:] if columns else rows:
        _add_row(contents, row, columns)

    return contents


def _delimiter(text: str) -> str:
    """Определить разделитель по первым строкам.

    Sniffer ошибается на файлах, где в тексте есть запятые, а разделитель —
    точка с запятой, поэтому его подсказку проверяем счётом: побеждает знак,
    который делит строки на одинаковое число колонок.
    """
    sample = "\n".join(text.splitlines()[:20])

    best = ","
    best_score = 0

    for candidate in _DELIMITERS:
        counts = [line.count(candidate) for line in sample.splitlines() if line.strip()]

        if not counts or counts[0] == 0:
            continue

        # Ровные строки — признак настоящего разделителя: у случайного знака
        # число вхождений от строки к строке скачет.
        score = counts[0] * sum(1 for count in counts if count == counts[0])

        if score > best_score:
            best, best_score = candidate, score

    return best


def _columns(header: list[str]) -> dict[str, int] | None:
    """Сопоставить заголовок с полями. None — заголовка нет."""
    names = [cell.strip().casefold().lstrip("﻿") for cell in header]

    mapping: dict[str, int] = {}

    for index, name in enumerate(names):
        for field, known in (
            ("source", _SOURCE_NAMES),
            ("target", _TARGET_NAMES),
            ("note", _NOTE_NAMES),
            ("kind", _KIND_NAMES),
            ("status", _STATUS_NAMES),
            ("reference", _REFERENCE_NAMES),
        ):
            if name in known and field not in mapping:
                mapping[field] = index

    # Заголовком считается строка, где нашлись обе главные колонки. Одной
    # мало: в словаре без заголовка первая строка вполне может начинаться
    # со слова «термин».
    if "source" in mapping and "target" in mapping:
        return mapping

    return None


def _add_row(contents: DictionaryContents, row: list[str], columns: dict[str, int] | None) -> None:
    def cell(field: str, position: int) -> str:
        index = columns[field] if columns and field in columns else position
        return row[index].strip() if index < len(row) else ""

    source = cell("source", 0)
    target = cell("target", 1)

    if not source or not target:
        contents.skip(f"нет термина или перевода: {' | '.join(row)[:80]}")
        return

    if len(source) > MAX_TERM_LENGTH or len(target) > MAX_TERM_LENGTH:
        contents.skip(f"строка длиннее {MAX_TERM_LENGTH} знаков: {source[:60]}")
        return

    kind = _KINDS.get(cell("kind", 3).casefold(), GlossaryEntryKind.TERM)

    contents.terms.append(
        ImportedTerm(
            source_term=source,
            target_term=target,
            kind=kind,
            status=_STATUSES.get(cell("status", 4).casefold(), GlossaryTermStatus.PROPOSED),
            note=cell("note", 2) or None,
            reference=cell("reference", 5) or None,
            expand_on_first_use=kind is GlossaryEntryKind.ABBREVIATION,
        )
    )
