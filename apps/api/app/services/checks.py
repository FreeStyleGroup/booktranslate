"""Проверки перевода.

Что именно проверять — вопрос не технический. Модель ошибается не там, где
ошибается человек: грамматика у неё безупречна, а число в предупреждении
может оказаться другим, обозначение — потерянным, а термин — переведённым
иначе, чем двумя абзацами выше. Всё это читается как гладкий текст, и
редактор, не сверяющий с исходником построчно, такого не увидит.

Поэтому проверки берут на себя ровно то, что машина видит лучше человека:
совпадение чисел, сохранность подстановок и разметки, употребление
терминов. Того, что человек видит лучше машины — верен ли перевод по
смыслу, — здесь нет и не будет.

Проверки чистые: строка на входе, находки на выходе. Ни базы, ни модели —
их можно прогнать на чём угодно и проверить тестом без окружения.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.models.segment import SegmentKind
from app.services.glossary import Glossary, Term, normalize_term

# Вес находки в оценке сегмента. Не абсолютная величина, а порядок: по нему
# редактор сортирует список и начинает с худшего. Пустой и непереведённый
# сегмент — это провал целиком, расхождение чисел близко к тому, нарушение
# глоссария и потерянная подстановка требуют внимания, но текст при них
# остаётся текстом.
WEIGHTS = {
    "empty": 1.0,
    "untranslated": 1.0,
    "numbers": 0.5,
    "glossary": 0.4,
    "placeholders": 0.4,
    "first_use": 0.2,
}

# Короткую строку сравнивать с исходником бессмысленно: «OK», «max» и
# «230 В» совпадают в обоих языках законно.
MIN_UNTRANSLATED_LENGTH = 25

_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)

# Число вместе с разделителями внутри: `1 250,5`, `1,250.5`, `2024`.
# Пробелы перечислены поимённо — обычный, неразрывный и узкий неразрывный:
# именно ими разделяют разряды, а `\s` затянул бы в число перевод строки.
_SPACES = "\u0020\u00a0\u202f"
_NUMBER = re.compile(rf"\d[\d{_SPACES}.,]*\d|\d")

# Подстановки и разметка, которые обязаны доехать до перевода без изменений.
_PLACEHOLDER = re.compile(
    r"\{[^{}\n]{0,60}\}"  # {0}, {name}
    r"|%[-+ #0-9.]*[sdifgxX]"  # %s, %d, %.2f
    r"|%\([A-Za-z_][\w]*\)[sdif]"  # %(name)s
    r"|</?[A-Za-z][^<>\n]{0,80}>"  # <b>, <br/>
)


@dataclass(frozen=True, slots=True)
class Finding:
    """Что не сошлось в сегменте."""

    check: str
    message: str

    @property
    def weight(self) -> float:
        return WEIGHTS.get(self.check, 0.3)


def run_checks(
    source_text: str, target_text: str, *, glossary: Glossary, kind: SegmentKind
) -> list[Finding]:
    """Проверить один сегмент."""
    if not target_text.strip():
        return [Finding("empty", "перевод пуст")]

    findings: list[Finding] = []

    if _looks_untranslated(source_text, target_text, kind):
        findings.append(Finding("untranslated", "перевод совпадает с исходником"))

    findings.extend(_number_findings(source_text, target_text))
    findings.extend(_placeholder_findings(source_text, target_text))
    findings.extend(_glossary_findings(source_text, target_text, glossary))

    return findings


def score(findings: Sequence[Finding]) -> float:
    """Оценка сегмента от нуля до единицы.

    Не претендует на измерение качества — это порядок сортировки: сегмент с
    расхождением чисел должен попасться редактору раньше, чем сегмент с
    неупотреблённым необязательным термином.
    """
    penalty = sum(finding.weight for finding in findings)

    return max(0.0, round(1.0 - penalty, 3))


def as_json(findings: Sequence[Finding]) -> dict[str, Any] | None:
    """Находки в том виде, в каком они лягут в сегмент."""
    if not findings:
        return None

    return {
        "score": score(findings),
        "findings": [{"check": item.check, "message": item.message} for item in findings],
    }


def _looks_untranslated(source_text: str, target_text: str, kind: SegmentKind) -> bool:
    """Перевод дословно повторяет исходник.

    Код и обозначения повторяют исходник законно, короткие строки — тоже:
    «230 В» и «max» в обоих языках выглядят одинаково. Строка без единой
    буквы (номер, формула, артикул) проверке не подлежит вовсе.
    """
    if kind is SegmentKind.CODE or len(source_text.strip()) < MIN_UNTRANSLATED_LENGTH:
        return False

    if not _LETTERS.search(source_text):
        return False

    return normalize_term(source_text) == normalize_term(target_text)


def _number_findings(source_text: str, target_text: str) -> list[Finding]:
    """Числа исходника обязаны быть в переводе.

    Проверяются оба направления: пропавшее число — это потерянное значение,
    а появившееся — придуманное. И то и другое в техническом тексте
    опаснее любой стилистики.
    """
    source_numbers = _numbers(source_text)
    target_numbers = _numbers(target_text)

    findings = []

    lost = sorted((source_numbers - target_numbers).elements())
    if lost:
        findings.append(Finding("numbers", "в переводе нет чисел: " + ", ".join(lost)))

    added = sorted((target_numbers - source_numbers).elements())
    if added:
        findings.append(Finding("numbers", "в переводе появились числа: " + ", ".join(added)))

    return findings


def _numbers(text: str) -> Counter[str]:
    return Counter(_canonical_number(match.group()) for match in _NUMBER.finditer(text))


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


def _placeholder_findings(source_text: str, target_text: str) -> list[Finding]:
    """Подстановки и разметка должны доехать без изменений.

    Потерянный `{0}` — это не опечатка, а строка, которая на экране покажет
    пустое место вместо значения; сломанный тег рушит вёрстку.
    """
    lost = Counter(_PLACEHOLDER.findall(source_text)) - Counter(_PLACEHOLDER.findall(target_text))

    if not lost:
        return []

    return [
        Finding("placeholders", "в переводе нет подстановок: " + ", ".join(sorted(lost.elements())))
    ]


def _glossary_findings(source_text: str, target_text: str, glossary: Glossary) -> list[Finding]:
    return [
        Finding("glossary", f"не употреблён термин «{term.target}» ({term.source})")
        for term in glossary.missing_in(source_text, target_text)
    ]


def first_use_finding(term: Term, target_text: str) -> Finding | None:
    """Раскрыта ли аббревиатура при первом употреблении.

    Правило технического текста: «маркет-мейкер (market maker, MM)», дальше
    просто MM. Читатель, встретивший MM без расшифровки, идёт искать её в
    интернете — и это провал перевода, а не читателя.

    Проверяется машинно-проверяемая часть: в первом употреблении рядом с
    переводом должна стоять сама исходная форма. Полнота расшифровки
    остаётся за человеком — её из словаря не вывести.
    """
    if term.source in target_text:
        return None

    return Finding(
        "first_use",
        f"при первом употреблении не введено сокращение «{term.source}»",
    )
