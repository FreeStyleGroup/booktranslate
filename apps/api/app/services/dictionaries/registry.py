"""Рабочий реестр бюро в DOCX.

Формат не стандартный, а тот, в котором терминология книги ведётся на самом
деле: документ со стилями абзацев `Entry`, `Definition` и `Meta`, по одной
тройке на запись.

    Entry       CH02-ABBR-004  ·  MM
    Definition  market maker — маркет-мейкер. Первое: «маркет-мейкер
                (market maker, MM)»; далее MM. В индексах формул оставлять MM.
    Meta        аббревиатура · требует унификации по книге · 2.1 Market Making
                · первый CH02-B0008; печ. 20, полный PDF 37. Связи: …

Поддержан потому, что это фактический вход: реестр главы существует до
всякого импорта, в нём двести решённых записей, и заставлять человека
перебивать их в таблицу — значит не получить их вовсе.

Разбор идёт по стилям, а не по виду текста: разделители внутри строки
(«·», «—») встречаются и в самих терминах, а стиль абзаца автор не ставит
случайно.
"""

import io
import re
from typing import Any

from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.services.dictionaries.base import DictionaryContents, DictionaryError, ImportedTerm

MAX_TERM_LENGTH = 300

# Разряд записи. Слева — как это называется в реестре.
_KINDS = {
    "аббревиатура": GlossaryEntryKind.ABBREVIATION,
    "общетекстовое сокращение": GlossaryEntryKind.ABBREVIATION,
    "сокращение": GlossaryEntryKind.ABBREVIATION,
    "математическое обозначение": GlossaryEntryKind.NOTATION,
    "обозначение участника": GlossaryEntryKind.NOTATION,
    "обозначение": GlossaryEntryKind.NOTATION,
    "имя площадки": GlossaryEntryKind.PROPER_NAME,
    "условное имя": GlossaryEntryKind.PROPER_NAME,
    "имя собственное": GlossaryEntryKind.PROPER_NAME,
}

# Состояние решения. «Оставить без перевода» стоит особняком: в реестре это
# записано в колонке статуса, но говорит оно не о том, договорились ли мы, а
# о том, что это за запись, — и превращается в разряд.
_STATUSES = {
    "предварительно рекомендован": GlossaryTermStatus.PROPOSED,
    "пропущенный термин": GlossaryTermStatus.PROPOSED,
    "подтверждено": GlossaryTermStatus.CONFIRMED,
    "подтверждён": GlossaryTermStatus.CONFIRMED,
    "требует перепроверки": GlossaryTermStatus.NEEDS_REVIEW,
    "исправить": GlossaryTermStatus.NEEDS_REVIEW,
    "требует дополнительного решения": GlossaryTermStatus.NEEDS_REVIEW,
    "требует унификации по книге": GlossaryTermStatus.NEEDS_UNIFICATION,
    "требует унификации": GlossaryTermStatus.NEEDS_UNIFICATION,
    "дубликат": GlossaryTermStatus.RETIRED,
}

_UNTRANSLATED = "оставить без перевода"

# Разряды, у которых перевод совпадает с исходником: обозначение μ остаётся
# μ, площадка NASDAQ остаётся NASDAQ. Описание из реестра при этом не
# теряется — оно уходит в примечание.
_KEEP_SOURCE = (
    GlossaryEntryKind.NOTATION,
    GlossaryEntryKind.PROPER_NAME,
    GlossaryEntryKind.DO_NOT_TRANSLATE,
)

_SEPARATORS = re.compile(r"\s*[·•]\s*")
_DASH = re.compile(r"\s+[—–]\s+")
_SENTENCE = re.compile(r"(?<=[.;])\s+")
_STYLES = ("entry", "definition", "meta")


def read_registry(data: bytes) -> DictionaryContents:
    try:
        import docx
    except ImportError as error:  # pragma: no cover — зависимость обязательная
        raise DictionaryError("Разбор DOCX недоступен") from error

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as error:  # noqa: BLE001 — чужой DOCX падает по-разному
        raise DictionaryError(f"Файл не открылся как DOCX: {error}") from error

    contents = DictionaryContents()
    entry: str | None = None
    definition: str | None = None

    for paragraph in document.paragraphs:
        style = _style_of(paragraph)
        text = paragraph.text.strip()

        if not text or style not in _STYLES:
            continue

        if style == "entry":
            # Запись без `Meta` до сих пор не закрыта: закрываем её тем, что
            # есть, иначе потеряется последняя строка файла и любая, где
            # автор не проставил третий абзац.
            _flush(contents, entry, definition, None)
            entry, definition = text, None
        elif style == "definition":
            definition = text
        else:
            _flush(contents, entry, definition, text)
            entry, definition = None, None

    _flush(contents, entry, definition, None)

    if not contents.terms and not contents.skipped:
        raise DictionaryError("В документе нет записей со стилями Entry и Definition")

    return contents


def _flush(
    contents: DictionaryContents, entry: str | None, definition: str | None, meta: str | None
) -> None:
    if entry is None:
        return

    identifier, source = _split_entry(entry)

    if not source:
        contents.skip(f"пустая запись: {entry[:60]}")
        return

    if definition is None:
        contents.skip(f"{identifier or source}: нет определения")
        return

    # Ни номера, ни пометок — это не запись реестра. В тех же документах
    # такими абзацами оформлены редакторские заметки о смежных понятиях
    # («liquidity trader / informed trader» с разбором различий), и в
    # словаре им делать нечего: «термин» там пара понятий через косую, а
    # «перевод» — предложение о том, чем они отличаются.
    if identifier is None and meta is None:
        contents.skip(f"не запись реестра, нет номера и пометок: {source[:60]}")
        return

    kind, status = _classify(meta, identifier)
    # Сначала первое предложение, и только потом тире. Обратный порядок
    # ломается на пояснениях вроде «позиция — для знаковой величины q»:
    # тире там есть, а расшифровки нет, и в перевод уезжал хвост фразы.
    expansion, target_text = _split_definition(_first_sentence(definition))
    target = source if kind in _KEEP_SOURCE else target_text

    if not target:
        contents.skip(f"{identifier or source}: не нашёлся перевод")
        return

    if len(source) > MAX_TERM_LENGTH or len(target) > MAX_TERM_LENGTH:
        contents.skip(f"{identifier or source}: строка длиннее {MAX_TERM_LENGTH} знаков")
        return

    contents.terms.append(
        ImportedTerm(
            source_term=source,
            target_term=target,
            kind=kind,
            status=status,
            # Определение целиком, а не остаток: переводчику нужны и
            # расшифровка, и правило употребления из реестра.
            note=definition,
            reference=_reference(identifier, meta),
            # Расшифровка есть — значит при первом употреблении её положено
            # раскрыть; так это и записано в самом реестре.
            expand_on_first_use=bool(expansion) and kind is GlossaryEntryKind.ABBREVIATION,
        )
    )


def _split_entry(entry: str) -> tuple[str | None, str]:
    """`CH02-ABBR-004 · MM` → идентификатор и сам термин."""
    parts = [part for part in _SEPARATORS.split(entry) if part.strip()]

    if len(parts) >= 2:
        return parts[0].strip(), " ".join(part.strip() for part in parts[1:])

    return None, entry.strip()


def _split_definition(definition: str) -> tuple[str | None, str]:
    """`market maker — маркет-мейкер. …` → расшифровка и остаток.

    Тире разделяет их только тогда, когда оно есть: у обычного термина
    определение начинается прямо с перевода.
    """
    parts = _DASH.split(definition, maxsplit=1)

    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    return None, definition.strip()


def _first_sentence(text: str) -> str:
    """Перевод — это первое предложение определения, дальше идёт пояснение."""
    head = _SENTENCE.split(text, maxsplit=1)[0].strip()

    return head.rstrip(".;").strip()


def _classify(
    meta: str | None, identifier: str | None
) -> tuple[GlossaryEntryKind, GlossaryTermStatus]:
    """Разряд и статус записи.

    Порядок важен: «оставить без перевода» из колонки статуса перебивает
    разряд, потому что говорит именно о том, что запись переносится как
    есть. Если разряд не узнан — смотрим на идентификатор: `-ABBR-` в нём
    означает реестр сокращений, а не терминов.
    """
    fields = [part.strip().casefold() for part in _SEPARATORS.split(meta or "") if part.strip()]

    kind = GlossaryEntryKind.TERM
    status = GlossaryTermStatus.PROPOSED

    if identifier and "-abbr-" in identifier.casefold():
        kind = GlossaryEntryKind.ABBREVIATION

    for value in fields:
        if value in _KINDS:
            kind = _KINDS[value]
        elif value in _STATUSES:
            status = _STATUSES[value]
        elif value == _UNTRANSLATED:
            kind = GlossaryEntryKind.DO_NOT_TRANSLATE
            status = GlossaryTermStatus.CONFIRMED

    return kind, status


def _reference(identifier: str | None, meta: str | None) -> str | None:
    """След, по которому запись находят в исходном реестре.

    Без него спор о термине через месяц начинается заново: номер записи и
    место первого вхождения — это то, к чему возвращаются.
    """
    location = ""

    if meta:
        found = re.search(r"перв\w*\s+[^;·]+", meta)
        if found:
            location = found.group().strip()

    parts = [part for part in (identifier, location) if part]

    return " · ".join(parts) if parts else None


def _style_of(paragraph: Any) -> str:
    # У абзаца может не быть стиля вовсе — тогда обращение к `.name` падает.
    style = getattr(paragraph, "style", None)

    return str(getattr(style, "name", "") or "").strip().casefold()
