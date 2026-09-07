"""TBX — обменный формат терминологических баз.

В нём отдают свои базы Microsoft Terminology, UNTERM и переводческие
системы, поэтому он и поддержан: это то, во что выгружается чужой словарь,
когда его отдают целиком, а не таблицей на сотню строк.

Разбор идёт защищённым парсером. XML из внешнего файла — это вход, которым
управляет не мы: документ с рекурсивно вложенными сущностями («billion
laughs») разворачивается в гигабайты в памяти, а внешняя сущность в
объявлении читает файл с диска сервера. Штатный `xml.etree` от первого не
защищён.

Формат живёт в двух несовместимых редакциях: в TBX 2 запись называется
`termEntry`, в TBX 3 — `conceptEntry`, а язык объявляется то `langSet`, то
`langSec`. Поддержаны обе: заказчик прислал файл, а не редакцию стандарта.
"""

from typing import Any

from defusedxml import ElementTree

from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.services.dictionaries.base import DictionaryContents, DictionaryError, ImportedTerm

MAX_TERM_LENGTH = 300

_ENTRIES = ("termentry", "conceptentry")
_LANGUAGES = ("langset", "langsec")
_TERMS = ("term",)
_NOTES = ("descrip", "note")

# Пометки, которыми в термбазах отмечают неприменимые варианты. Запись с
# такой пометкой в словарь идти не должна: «не используйте это слово» —
# указание противоположное тому, как работает наш глоссарий.
_FORBIDDEN = frozenset({"notrecommended", "obsolete", "superseded", "deprecated", "forbidden"})


def read_tbx(data: bytes, *, source_language: str, target_language: str) -> DictionaryContents:
    try:
        root = ElementTree.fromstring(data)
    except Exception as error:  # noqa: BLE001 — разбор чужого XML падает по-разному
        raise DictionaryError(f"Файл не разобрался как XML: {error}") from error

    contents = DictionaryContents()
    entries = [node for node in root.iter() if _name(node) in _ENTRIES]

    if not entries:
        raise DictionaryError("В файле нет терминологических записей TBX")

    for entry in entries:
        _add_entry(contents, entry, source_language, target_language)

    return contents


def _add_entry(
    contents: DictionaryContents, entry: Any, source_language: str, target_language: str
) -> None:
    by_language: dict[str, list[Any]] = {}

    for node in entry.iter():
        if _name(node) not in _LANGUAGES:
            continue

        language = _language_of(node)
        if language:
            by_language.setdefault(language, []).append(node)

    source = _term_in(by_language, source_language)
    target = _term_in(by_language, target_language)

    if source is None or target is None:
        contents.skip(f"нет пары {source_language} → {target_language} в записи")
        return

    if len(source) > MAX_TERM_LENGTH or len(target) > MAX_TERM_LENGTH:
        contents.skip(f"строка длиннее {MAX_TERM_LENGTH} знаков: {source[:60]}")
        return

    contents.terms.append(
        ImportedTerm(
            source_term=source,
            target_term=target,
            status=GlossaryTermStatus.PROPOSED,
            note=_note_in(entry),
            kind=GlossaryEntryKind.TERM,
        )
    )


def _term_in(by_language: dict[str, list[Any]], language: str) -> str | None:
    """Термин на нужном языке.

    Точное совпадение кода бывает редко: в базах пишут `en-US` и `ru-RU`, а
    просят обычно `en` и `ru`. Поэтому подходящие варианты берутся по
    убыванию точности — сперва тот же код, затем уточнение региона, и лишь
    потом любой другой регион того же языка. Порядок важен там, где в базе
    есть и `zh-Hans`, и `zh-Hant`: спутать их нельзя, а `en-GB` вместо
    `en-US` для терминологии — то же самое.
    """
    wanted = language.casefold().replace("_", "-")

    ranked = sorted(
        (rank, code) for code in by_language if (rank := _closeness(code, wanted)) is not None
    )

    for _, code in ranked:
        for node in by_language[code]:
            if _is_forbidden(node):
                continue

            for child in node.iter():
                if _name(child) in _TERMS and (child.text or "").strip():
                    return str(child.text).strip()

    return None


def _closeness(code: str, wanted: str) -> int | None:
    """Насколько код языка из файла близок к запрошенному. None — не подходит."""
    if code == wanted:
        return 0

    if code.startswith(wanted + "-") or wanted.startswith(code + "-"):
        return 1

    if code.split("-")[0] == wanted.split("-")[0]:
        return 2

    return None


def _is_forbidden(node: Any) -> bool:
    for child in node.iter():
        if _name(child) not in ("termnote", "descrip"):
            continue

        value = (child.text or "").strip().casefold().replace(" ", "").replace("-", "")
        if value in _FORBIDDEN:
            return True

    return False


def _note_in(entry: Any) -> str | None:
    for node in entry.iter():
        if _name(node) in _NOTES and (node.text or "").strip():
            return str(node.text).strip()

    return None


def _language_of(node: Any) -> str:
    for key, value in node.attrib.items():
        if _strip_namespace(key).casefold() == "lang":
            return str(value).casefold().replace("_", "-")

    return ""


def _name(node: Any) -> str:
    return _strip_namespace(str(node.tag)).casefold()


def _strip_namespace(name: str) -> str:
    """`{http://…}termEntry` и `tbx:termEntry` → `termEntry`."""
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1]
