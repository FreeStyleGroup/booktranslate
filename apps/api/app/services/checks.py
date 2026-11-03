"""Детерминированные проверки перевода.

Что именно проверять — вопрос не технический. Модель ошибается не так, как ошибается человек:
грамматика у неё безупречна, а значение может оказаться другим, обозначение — потерянным, термин
— переведённым иначе, чем двумя абзацами выше. Всё это читается как правильный текст, и редактор,
не сверяющий с исходником построчно, такое пропустит.

Поэтому проверки берут на себя ровно то, что машина видит надёжнее: числа и их знаки, диапазоны,
единицы, имена из кода, ссылки на рисунки и таблицы, защищённые объекты, нумерацию и термины.
Смысла здесь нет и не будет: он у отдельного прохода (`services/qa_runner.py`).

Проверки чистые: строка на входе, находки на выходе, без базы и без сети. Находка сама ничего не
решает: она становится замечанием реестра, а решает человек. Цена ложной тревоги здесь — лишняя
строка, которую отклонят один раз: отклонённая находка той же редакции второй раз не появится.

`CHECK_PROFILE_VERSION` меняется вместе с составом проверок: по нему видно, какими правилами
проверена редакция, и формальная отметка старой версии перестаёт действовать сама.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.models.block import BlockKind
from app.models.issue import IssueCategory, IssueSeverity
from app.services.glossary import Glossary, Term, normalize_term

CHECK_PROFILE_VERSION = "2026.11.1"

# Короткую строку сравнивать с исходником бессмысленно: «OK», «max» и «230 В» совпадают в обоих
# языках законно.
MIN_UNTRANSLATED_LENGTH = 25

_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)

# Число вместе с разделителями внутри: `1 250,5`, `1,250.5`, `2024`. Пробелы перечислены поимённо —
# обычный, неразрывный и узкий неразрывный: именно ими разделяют разряды, а `\s` затянул бы в число
# перевод строки.
_SPACES = "\u0020\u00a0\u202f"
_NUMBER = re.compile(rf"\d[\d{_SPACES}.,]*\d|\d")

# Число без пробелов внутри: для знаков, диапазонов и единиц пробел уже что-то значит.
_TIGHT = r"\d[\d.,]*\d|\d"

# Знак — только там, где слева нет ни слова, ни числа: `CH-47` и `5-10` знака не содержат.
_SIGNED = re.compile(rf"(?<![\w.,)\]])([-−–+])({_TIGHT})")
_SIGN_WORD = re.compile(rf"\b(минус|minus|плюс|plus)\s+({_TIGHT})", re.IGNORECASE)

_RANGE = re.compile(
    rf"(?<![\w.,-])({_TIGHT})\s?(?:[-–—]|\.\.\.?|…)\s?({_TIGHT})(?![\w-])"
    rf"|(?<![\w.,])({_TIGHT})\s+(?:to|до)\s+({_TIGHT})(?![\w-])",
    re.IGNORECASE,
)

_TOKEN = re.compile(r"⟦\d+⟧")

# Подстановки и разметка, которые обязаны доехать до перевода без изменений.
_PLACEHOLDER = re.compile(
    r"\{[^{}\n]{0,60}\}"  # {0}, {name}
    r"|%[-+ #0-9.]*[sdifgxX]"  # %s, %d, %.2f
    r"|%\([A-Za-z_][\w]*\)[sdif]"  # %(name)s
    r"|</?[A-Za-z][^<>\n]{0,80}>"  # <b>, <br/>
)

# Имена из кода: `max_speed`, `CONFIG_PATH`, `getValue`, `open()`. Переводу они не подлежат.
_IDENTIFIER = re.compile(
    r"(?<![\w.-])(?:[A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z_]\w*\(\))"
)

# Единица и все формы, которыми её законно написать в переводе. Полные слова — основами: русский
# склоняет, и «5 метров» такая же верная запись, как «5 м».
_UNITS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("mm", "мм"), ("миллиметр",)),
    (("cm", "см"), ("сантиметр",)),
    (("km", "км"), ("километр",)),
    (("m", "м"), ("метр",)),
    (("kg", "кг"), ("килограмм",)),
    (("mg", "мг"), ("миллиграмм",)),
    (("g", "г"), ("грамм",)),
    (("kW", "кВт"), ("киловатт",)),
    (("W", "Вт"), ("ватт",)),
    (("kV", "кВ"), ("киловольт",)),
    (("mV", "мВ"), ("милливольт",)),
    (("V", "В"), ("вольт",)),
    (("mA", "мА"), ("миллиампер",)),
    (("A", "А"), ("ампер",)),
    (("GHz", "ГГц"), ("гигагерц",)),
    (("MHz", "МГц"), ("мегагерц",)),
    (("kHz", "кГц"), ("килогерц",)),
    (("Hz", "Гц"), ("герц",)),
    (("MPa", "МПа"), ("мегапаскал",)),
    (("kPa", "кПа"), ("килопаскал",)),
    (("Pa", "Па"), ("паскал",)),
    (("bar", "бар"), ("бар",)),
    (("Nm", "N·m", "Н·м", "Нм"), ("ньютон-метр",)),
    (("kN", "кН"), ("килоньютон",)),
    (("N", "Н"), ("ньютон",)),
    (("ms", "мс"), ("миллисекунд",)),
    (("min", "мин"), ("минут",)),
    (("s", "с", "сек"), ("секунд",)),
    (("h", "ч"), ("час",)),
    (("ml", "mL", "мл"), ("миллилитр",)),
    (("l", "L", "л"), ("литр",)),
    (("TB", "ТБ"), ("терабайт",)),
    (("GB", "ГБ"), ("гигабайт",)),
    (("MB", "МБ"), ("мегабайт",)),
    (("KB", "kB", "КБ", "кБ"), ("килобайт",)),
    (("rpm", "об/мин"), ("оборот",)),
    (("°C", "℃"), ("градус",)),
    (("%",), ("процент",)),
)
_UNIT_FORMS = sorted(
    ((form, index) for index, (forms, _) in enumerate(_UNITS) for form in forms),
    key=lambda pair: len(pair[0]),
    reverse=True,
)
# Единица сразу за числом. Число ищется отдельно: в нём могут быть пробелы (`1 250 rpm`).
_UNIT_AT = re.compile(
    rf"[{_SPACES}]?(" + "|".join(re.escape(form) for form, _ in _UNIT_FORMS) + r")(?![\w])"
)
_WORD_AT = re.compile(rf"[{_SPACES}]?(\S*)")
_UNIT_INDEX = dict(_UNIT_FORMS)

# Виды ссылок и слова, которыми их называют на обоих языках. Основами: падежи русского законны.
_REFERENCES: tuple[tuple[str, str], ...] = (
    ("рисунок", r"figures?|figs?\.?|рис\w*\.?"),
    ("таблицу", r"tables?|табл\w*\.?"),
    ("раздел", r"sections?|sec\.|§|раздел\w*|разд\.|параграф\w*"),
    ("главу", r"chapters?|ch\.|глав\w*|гл\."),
    ("листинг", r"listings?|листинг\w*"),
    ("формулу", r"equations?|eqs?\.|formulas?|формул\w*|уравнени\w*"),
    ("приложение", r"appendix|appendices|приложени\w*"),
)
# Метка — номер или заглавная буква. Регистр важен: «таблица с данными» ссылкой не является.
_REFERENCE_LABEL = r"\(?(\d+(?:\.\d+)*[a-zа-я]?|[A-ZА-Я])\)?"
_REFERENCE = tuple(
    (name, re.compile(rf"(?<![\w])(?i:{words})[{_SPACES}]*{_REFERENCE_LABEL}(?![\w])"))
    for name, words in _REFERENCES
)

_LIST_MARKER = re.compile(
    r"^\s*(?:\(?(\d+(?:\.\d+)*)[.)]|\(?([A-Za-zА-Яа-яЁё])[.)]|\(([ivxlc]+)\))\s"
)

# Латинская буква маркера и её русская замена: `a)` законно становится `а)`.
_LATIN_TO_CYRILLIC = str.maketrans("abcdefgh", "абвгдежз")

# Правила, по которым находка не требует регистрации. Находка всё равно записывается: так видно,
# что её нашли и почему не завели замечание.
OPTIONAL_TERM = "optional_term"
LOCALIZED_MARKER = "localized_marker"


@dataclass(frozen=True, slots=True)
class Finding:
    """Что не сошлось в тексте блока."""

    check: str
    message: str
    category: IssueCategory
    severity: IssueSeverity
    # Правило, по которому регистрировать незачем. Пусто — находка становится замечанием.
    not_required: str | None = None


def run_checks(
    source_text: str,
    target_text: str,
    *,
    glossary: Glossary,
    kind: BlockKind,
    protected: Sequence[str] = (),
    first_use: Iterable[Term] = (),
) -> list[Finding]:
    """Проверить перевод одного блока.

    `protected` — формулы и код внутри абзаца, как они стоят в исходнике; `first_use` — термины с
    правилом первого употребления, которые в главе встречаются здесь впервые.
    """
    if not target_text.strip():
        return [Finding("empty", "перевод пуст", IssueCategory.TRANSLATION, IssueSeverity.CRITICAL)]

    # Листинг сверяется знак в знак, и никакие другие сравнения ему не нужны.
    if kind is BlockKind.CODE:
        return _code_findings(source_text, target_text)

    findings: list[Finding] = []

    if _looks_untranslated(source_text, target_text):
        findings.append(
            Finding(
                "untranslated",
                "перевод совпадает с исходником",
                IssueCategory.TRANSLATION,
                IssueSeverity.MAJOR,
            )
        )

    findings.extend(_number_findings(source_text, target_text))
    findings.extend(_sign_findings(source_text, target_text))
    findings.extend(_range_findings(source_text, target_text))
    findings.extend(_unit_findings(source_text, target_text))
    findings.extend(_identifier_findings(source_text, target_text))
    findings.extend(_reference_findings(source_text, target_text))
    findings.extend(_object_findings(target_text, protected))
    findings.extend(_placeholder_findings(source_text, target_text))

    if kind is BlockKind.LIST_ITEM:
        findings.extend(_list_findings(source_text, target_text))

    findings.extend(_glossary_findings(source_text, target_text, glossary))
    findings.extend(
        finding
        for finding in (first_use_finding(term, target_text) for term in first_use)
        if finding is not None
    )

    return findings


def protected_changes(
    source_text: str,
    base_text: str,
    new_text: str,
    *,
    glossary: Glossary,
    protected: Sequence[str] = (),
) -> list[str]:
    """Что литературная правка изменила из того, что менять ей нельзя.

    Сравнивается с прежней редакцией, а не с исходником: правка отвечает только за то, что сломала
    сама. Если число было неверным и раньше, это забота проверок, а не этой защиты.
    """
    changes: list[str] = []

    base_numbers, new_numbers = _numbers(base_text), _numbers(new_text)
    lost = sorted((base_numbers - new_numbers).elements())
    added = sorted((new_numbers - base_numbers).elements())

    if lost:
        changes.append("пропали числа " + ", ".join(lost))
    if added:
        changes.append("появились числа " + ", ".join(added))

    signs = _signed(base_text) - _signed(new_text)
    if signs:
        changes.append("изменился знак числа")

    for name, pattern, finder in (
        ("подстановки", _PLACEHOLDER, _PLACEHOLDER.findall),
        ("имена из кода", _IDENTIFIER, _IDENTIFIER.findall),
    ):
        gone = Counter(finder(base_text)) - Counter(finder(new_text))
        if pattern is not None and gone:
            changes.append(f"пропали {name}: " + ", ".join(sorted(gone)))

    for name, reference in _REFERENCE:
        target = {_reference_label(label) for label in reference.findall(new_text)}
        gone_refs = [
            label for label in reference.findall(base_text) if _reference_label(label) not in target
        ]
        if gone_refs:
            changes.append(f"пропала ссылка на {name}: " + ", ".join(gone_refs))

    gone_spans = [item for item in protected if item in base_text and item not in new_text]
    if gone_spans:
        changes.append("пропали защищённые фрагменты: " + ", ".join(gone_spans))

    if "⟦" in new_text:
        changes.append("в тексте остался заменитель объекта")

    before = {term.source for term in glossary.missing_in(source_text, base_text)}
    terms = [
        term.target
        for term in glossary.missing_in(source_text, new_text)
        if term.source not in before
    ]
    if terms:
        changes.append("пропали обязательные термины: " + ", ".join(terms))

    return changes


def _code_findings(source_text: str, target_text: str) -> list[Finding]:
    if source_text == target_text:
        return []

    return [
        Finding(
            "code_changed",
            "листинг отличается от исходника: он переносится знак в знак",
            IssueCategory.CODE,
            IssueSeverity.CRITICAL,
        )
    ]


def _looks_untranslated(source_text: str, target_text: str) -> bool:
    """Перевод дословно повторяет исходник.

    Короткие строки повторяют его законно: «230 В» и «max» в обоих языках выглядят одинаково.
    Строка без единой буквы (номер, формула, артикул) проверке не подлежит вовсе.
    """
    if len(source_text.strip()) < MIN_UNTRANSLATED_LENGTH:
        return False

    if not _LETTERS.search(source_text):
        return False

    return normalize_term(source_text) == normalize_term(target_text)


def _number_findings(source_text: str, target_text: str) -> list[Finding]:
    """Числа исходника обязаны быть в переводе.

    Проверяются оба направления: пропавшее число — это потерянное значение, а появившееся —
    придуманное. И то и другое в техническом тексте опаснее любой стилистики.
    """
    source_numbers = _numbers(source_text)
    target_numbers = _numbers(target_text)

    findings = []

    lost = sorted((source_numbers - target_numbers).elements())
    if lost:
        findings.append(
            Finding(
                "numbers",
                "в переводе нет чисел: " + ", ".join(lost),
                IssueCategory.NUMBER,
                IssueSeverity.CRITICAL,
            )
        )

    added = sorted((target_numbers - source_numbers).elements())
    if added:
        findings.append(
            Finding(
                "numbers",
                "в переводе появились числа: " + ", ".join(added),
                IssueCategory.NUMBER,
                IssueSeverity.CRITICAL,
            )
        )

    return findings


def _signed(text: str) -> Counter[tuple[str, str]]:
    found: Counter[tuple[str, str]] = Counter()

    for sign, value in _SIGNED.findall(text):
        found["+" if sign == "+" else "-", _canonical_number(value)] += 1

    for word, value in _SIGN_WORD.findall(text):
        found["+" if word.casefold() in ("плюс", "plus") else "-", _canonical_number(value)] += 1

    return found


def _sign_findings(source_text: str, target_text: str) -> list[Finding]:
    """Минус, потерянный у температуры, меняет смысл и не выглядит ошибкой.

    Сообщается только о числах, которые в переводе есть: пропавшее целиком — уже забота проверки
    чисел, и двух находок на одно и то же здесь не нужно.
    """
    source = _signed(source_text)
    target = _signed(target_text)
    numbers = _numbers(target_text)

    lost = [
        f"{sign}{value}" for sign, value in sorted((source - target).elements()) if numbers[value]
    ]
    added = [
        f"{sign}{value}"
        for sign, value in sorted((target - source).elements())
        if _numbers(source_text)[value]
    ]

    if not lost and not added:
        return []

    return [
        Finding(
            "signs",
            "знак числа не сохранён: " + ", ".join(lost or added),
            IssueCategory.NUMBER,
            IssueSeverity.CRITICAL,
        )
    ]


def _ranges(text: str) -> set[tuple[str, str]]:
    found = set()

    for match in _RANGE.finditer(text):
        first, second = (match.group(1), match.group(2))

        if first is None:
            first, second = (match.group(3), match.group(4))

        found.add((_canonical_number(first), _canonical_number(second)))

    return found


def _range_findings(source_text: str, target_text: str) -> list[Finding]:
    """Границы диапазона на месте, но он перестал быть диапазоном или перевернулся."""
    target = _ranges(target_text)
    numbers = _numbers(target_text)

    lost = [
        f"{first}–{second}"
        for first, second in sorted(_ranges(source_text) - target)
        if numbers[first] and numbers[second]
    ]

    if not lost:
        return []

    return [
        Finding(
            "ranges",
            "диапазон не сохранён: " + ", ".join(lost),
            IssueCategory.NUMBER,
            IssueSeverity.MAJOR,
        )
    ]


def _unit_findings(source_text: str, target_text: str) -> list[Finding]:
    """Единица при числе. `5 mm` законно становится `5 мм` и `5 миллиметров`, но не `5 см`."""
    numbers = _numbers(target_text)
    missing = []

    for number in _NUMBER.finditer(source_text):
        unit = _UNIT_AT.match(source_text, number.end())

        if unit is None:
            continue

        value = _canonical_number(number.group())

        # Пропавшее число — забота проверки чисел.
        if not numbers[value]:
            continue

        if not _has_unit(target_text, value, _UNIT_INDEX[unit.group(1)]):
            missing.append(f"{number.group()} {unit.group(1)}")

    if not missing:
        return []

    return [
        Finding(
            "units",
            "у числа не та единица: " + ", ".join(missing),
            IssueCategory.NUMBER,
            IssueSeverity.MAJOR,
        )
    ]


def _has_unit(text: str, value: str, index: int) -> bool:
    forms, stems = _UNITS[index]

    for number in _NUMBER.finditer(text):
        if _canonical_number(number.group()) != value:
            continue

        following = _WORD_AT.match(text, number.end())
        word = following.group(1).rstrip('.,;:!?)»"]') if following is not None else ""

        if word in forms or any(word.casefold().startswith(stem) for stem in stems):
            return True

    return False


def _identifier_findings(source_text: str, target_text: str) -> list[Finding]:
    """Имя из кода переносится дословно: переведённое, оно перестаёт существовать."""
    lost = Counter(_IDENTIFIER.findall(source_text)) - Counter(_IDENTIFIER.findall(target_text))

    if not lost:
        return []

    return [
        Finding(
            "variables",
            "в переводе нет имён из кода: " + ", ".join(sorted(lost)),
            IssueCategory.CODE,
            IssueSeverity.MAJOR,
        )
    ]


def _reference_findings(source_text: str, target_text: str) -> list[Finding]:
    """Ссылка «Figure 3.1» должна остаться ссылкой на тот же номер и того же вида."""
    lost: list[str] = []

    for name, pattern in _REFERENCE:
        target = {_reference_label(label) for label in pattern.findall(target_text)}

        lost.extend(
            f"{name} {label}"
            for label in pattern.findall(source_text)
            if _reference_label(label) not in target
        )

    if not lost:
        return []

    return [
        Finding(
            "cross_references",
            "ссылка не сохранена: " + ", ".join(lost),
            IssueCategory.CROSS_REFERENCE,
            IssueSeverity.MAJOR,
        )
    ]


def _reference_label(label: str) -> str:
    """Буква приложения при переводе меняет алфавит: `Appendix B` — это `Приложение Б`."""
    return "буква" if label.isalpha() else label.casefold()


def _object_findings(target_text: str, protected: Sequence[str]) -> list[Finding]:
    """Формула и код внутри абзаца и заменители, которые не вернулись на место."""
    findings = []

    if "⟦" in target_text:
        findings.append(
            Finding(
                "object_placeholders",
                "в тексте остался заменитель объекта",
                IssueCategory.TECHNICAL,
                IssueSeverity.CRITICAL,
            )
        )

    lost = [item for item in protected if item not in target_text]
    if lost:
        findings.append(
            Finding(
                "object_placeholders",
                "в переводе нет защищённых фрагментов: " + ", ".join(lost),
                IssueCategory.FORMULA,
                IssueSeverity.CRITICAL,
            )
        )

    return findings


def _placeholder_findings(source_text: str, target_text: str) -> list[Finding]:
    """Подстановки и разметка должны доехать без изменений.

    Потерянный `{0}` — это не опечатка, а строка, которая на экране покажет пустое место вместо
    значения; сломанный тег рушит вёрстку.
    """
    lost = Counter(_PLACEHOLDER.findall(source_text)) - Counter(_PLACEHOLDER.findall(target_text))

    if not lost:
        return []

    return [
        Finding(
            "placeholders",
            "в переводе нет подстановок: " + ", ".join(sorted(lost.elements())),
            IssueCategory.TECHNICAL,
            IssueSeverity.MAJOR,
        )
    ]


def _list_findings(source_text: str, target_text: str) -> list[Finding]:
    """Номер пункта: на него ссылается остальной текст."""
    source = _LIST_MARKER.match(source_text)

    if source is None:
        return []

    target = _LIST_MARKER.match(target_text)

    if target is None:
        return [_list_finding(f"у пункта пропал номер: {source.group().strip()}")]

    number, letter, roman = source.groups()
    target_number, target_letter, target_roman = target.groups()

    if number != target_number or roman != target_roman:
        return [_list_finding(f"номер пункта изменился: {source.group().strip()}")]

    if letter == target_letter:
        return []

    # Буква маркера законно меняется на русскую, но считать её тем же самым правило не обязывает.
    if letter is not None and target_letter == letter.translate(_LATIN_TO_CYRILLIC):
        return [
            Finding(
                "list_numbering",
                f"буква пункта заменена на русскую: {source.group().strip()}",
                IssueCategory.TECHNICAL,
                IssueSeverity.MINOR,
                not_required=LOCALIZED_MARKER,
            )
        ]

    return [_list_finding(f"номер пункта изменился: {source.group().strip()}")]


def _list_finding(message: str) -> Finding:
    return Finding("list_numbering", message, IssueCategory.TECHNICAL, IssueSeverity.MAJOR)


def _glossary_findings(source_text: str, target_text: str, glossary: Glossary) -> list[Finding]:
    required = [
        Finding(
            "glossary",
            f"не употреблён термин «{term.target}» ({term.source})",
            IssueCategory.TERMINOLOGY,
            IssueSeverity.MAJOR,
        )
        for term in glossary.missing_in(source_text, target_text)
    ]
    hints = [
        Finding(
            "glossary",
            f"не употреблён необязательный термин «{term.target}» ({term.source})",
            IssueCategory.TERMINOLOGY,
            IssueSeverity.MINOR,
            not_required=OPTIONAL_TERM,
        )
        for term in glossary.optional_missing_in(source_text, target_text)
    ]

    return [*required, *hints]


def first_use_finding(term: Term, target_text: str) -> Finding | None:
    """Раскрыта ли аббревиатура при первом употреблении.

    Правило технического текста: «маркет-мейкер (market maker, MM)», дальше просто MM. Читатель,
    встретивший MM без расшифровки, идёт искать её в интернете — и это провал перевода, а не
    читателя.

    Проверяется машинно-проверяемая часть: в первом употреблении рядом с переводом должна стоять
    сама исходная форма. Полнота расшифровки остаётся за человеком — её из словаря не вывести.
    """
    if term.source in target_text:
        return None

    return Finding(
        "first_use",
        f"при первом употреблении не введено сокращение «{term.source}»",
        IssueCategory.TERMINOLOGY,
        IssueSeverity.MINOR,
    )


def _numbers(text: str) -> Counter[str]:
    # Цифра в оставшемся заменителе — не число текста: о нём сообщит своя проверка.
    plain = _TOKEN.sub("", text)

    return Counter(_canonical_number(match.group()) for match in _NUMBER.finditer(plain))


def _canonical_number(raw: str) -> str:
    """Привести число к виду, не зависящему от языка записи.

    Разделитель тысяч и десятичный знак в русском и английском поменяны
    местами: `1,250.5` и `1 250,5` — одно и то же число. Без приведения
    проверка ругалась бы на каждый правильно переведённый десятичный дробный.

    Неоднозначность `1,000` (тысяча по-английски, единица с тремя нулями
    после запятой по-русски) решена в пользу тысяч: так пишут несравнимо
    чаще, а цена ошибки здесь — лишняя строка в списке находок.
    """
    text = raw
    for space in _SPACES:
        text = text.replace(space, "")

    if "." in text and "," in text:
        # Десятичный — тот разделитель, который стоит последним.
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        text = text.replace(thousands, "").replace(decimal, ".")
    else:
        for separator in (".", ","):
            if separator not in text:
                continue

            head, _, tail = text.rpartition(separator)
            # Ровно три цифры после знака и что-то перед ним — это тысячи.
            if len(tail) == 3 and head and separator not in head:
                text = head + tail
            else:
                text = text.replace(separator, ".")

    try:
        value = float(text)
    except ValueError:
        return raw.strip()

    # Целое печатается без дробной части, дробное — без хвостовых нулей:
    # «1.50» и «1.5» это одно число.
    return str(int(value)) if value.is_integer() else repr(value)
