"""Извлечение терминов из самого документа.

Терминологический проход идёт **до** перевода, и это не оптимизация, а
условие качества. Модель, встречая `housing` в сорока разных сегментах,
сорок раз решает заново — и в главе 2 получается «корпус», а в главе 7
«кожух». Ни один из вариантов не ошибка сам по себе; ошибка в том, что их
два. Читатель технического текста спотыкается именно об это, а вычитка
такого расхождения стоит дороже перевода.

Поэтому термины книги сначала собираются списком, решаются один раз — и
дальше уходят в каждый запрос как ограничение и проверяются в ответе.

Извлечение намеренно обходится без морфологии и без внешних словарей: оно
не обязано быть точным, оно обязано быть полным и дешёвым. Отсеивать
лишнее человеку быстро, а термин, которого в списке нет, он не заметит и
не решит. Порог частоты и ранжирование существуют ровно для того, чтобы
сверху списка стояло то, что действительно повторяется.

Что достаётся из текста:

* **словосочетания** — по частоте, с поправкой на вложенность: если
  `check valve` встретился десять раз, то из двенадцати вхождений `valve`
  самостоятельных всего два, и подавать их как равнозначные кандидаты
  значит топить список в шуме;
* **аббревиатуры** — с расшифровкой, если она есть в тексте: `Programmable
  Logic Controller (PLC)` даёт не только `PLC`, но и то, что за ним стоит,
  а без расшифровки переводчик аббревиатуры угадывает;
* **обозначения стандартов** — `ISO 9001`, `EN 60204-1`, `ГОСТ Р 52931`:
  их не переводят никогда, и попадать они должны в словарь непереводимого.
"""

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.models.memory import GlossaryEntryKind

# Служебные слова. Термин не начинается и не кончается предлогом или
# артиклем: «of the valve» — это не термин, а обрывок фразы. Список
# сознательно короткий и покрывает две рабочие пары языков сразу: длинный
# частотный словарь здесь ничего не добавит, потому что решает не он, а
# порог частоты и вложенность.
_STOPWORD_LIST = """
    a an the and or but if then than that this these those of in on at by for from to
    with without into onto over under after before during between about as is are was
    were be been being it its their his her our your my no not all any each such same
    other more most less least when where which who whom what how why can could may
    might must shall should will would do does did done use used using see also
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если
    уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
    может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз
    тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом
    один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец
    два об другой хоть после над больше тот через эти нас про всего них какая много
    разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой
    им более всегда конечно всю между
"""

_STOPWORDS = frozenset(_STOPWORD_LIST.split())

# Римские цифры: `II`, `IV`, `XVIII` подходят под шаблон аббревиатуры, но
# аббревиатурами не являются — это нумерация глав и разделов.
_ROMAN = re.compile(r"^[IVXLCDM]+$")

# Аббревиатура: две и больше заглавных подряд, возможно с цифрами и одним
# дефисом. `RS-485`, `ПЛК`, `HMI`, `IP67`. Одна буква не годится: под неё
# подходит любой инициал.
_ABBREVIATION = re.compile(r"(?<![\w])[A-ZА-ЯЁ][A-ZА-ЯЁ0-9]{1,9}(?:-[A-ZА-ЯЁ0-9]{1,6})?(?![\w])")

# Обозначение стандарта. Номер обязателен: без него `ISO` — обычная
# аббревиатура, а вот `ISO 9001` целиком переносится в перевод как есть.
_STANDARD = re.compile(
    r"(?<![\w])"
    r"(?:ISO|IEC|EN|DIN|ANSI|ASTM|ASME|JIS|BS|NF|UL|CE|ГОСТ|ТУ|СП|СНиП|СанПиН|РД|ОСТ)"
    r"(?:\s?Р)?"
    r"[\s ]?\d[\d./\-–:]*\d|"
    r"(?<![\w])"
    r"(?:ISO|IEC|EN|DIN|ANSI|ASTM|ASME|JIS|BS|NF|UL|CE|ГОСТ|ТУ|СП|СНиП|СанПиН|РД|ОСТ)"
    r"[\s ]?\d"
    r"(?![\w])"
)

# Слово для составления словосочетаний. Дефис внутри слова сохраняется:
# «пневмо-гидравлический» — одно слово, а не два.
_TOKEN = re.compile(r"[^\W\d_][\w\-]*", re.UNICODE)

MAX_TERM_WORDS = 4
SAMPLE_RADIUS = 90

# Текст документа вместе с его порядковым номером.
_Chunk = tuple[int, str]


@dataclass(frozen=True, slots=True)
class Candidate:
    """Кандидат в словарь: что нашли, сколько раз и где именно."""

    source: str
    kind: GlossaryEntryKind
    frequency: int
    # Кусок текста вокруг первого вхождения. Без него решать по голому
    # списку нельзя: `head` в одной книге — «головка», в другой «оголовок»,
    # и различает их только контекст.
    sample: str
    # Расшифровка аббревиатуры, если она нашлась в тексте.
    expansion: str | None = None
    # Номер текста, в котором термин встретился впервые. Дальше становится
    # номером сегмента: в рабочих реестрах первое вхождение указывают всегда,
    # потому что спор о термине решается возвратом к этому месту.
    first_index: int = 0
    # Чем выше, тем раньше термин стоит в списке. Учитывает частоту и длину:
    # многословный термин ценнее одиночного слова той же частоты, потому
    # что именно на нём модель ошибается.
    score: float = 0.0


@dataclass(slots=True)
class _Sighting:
    """Накопленное по одному кандидату за проход по тексту."""

    count: int = 0
    surfaces: Counter[str] = field(default_factory=Counter)
    sample: str = ""
    expansion: str | None = None
    first_index: int = 0


def extract(texts: Iterable[str], *, min_frequency: int = 2, limit: int = 400) -> list[Candidate]:
    """Собрать кандидатов в словарь из текстов документа.

    `min_frequency` — сколько раз слово или сочетание должно встретиться,
    чтобы попасть в список. Единица означала бы «весь текст словами», и
    список стал бы нечитаемым; двойка отсекает случайное и оставляет то,
    что в документе действительно повторяется.
    """
    # Индекс исходного текста сохраняется: по нему потом находят сегмент, в
    # котором термин встретился впервые.
    chunks = [(index, text) for index, text in enumerate(texts) if text and text.strip()]

    abbreviations = _abbreviations(chunks)
    standards = _standards(chunks)

    # Что уже разобрано как аббревиатура или стандарт, в словосочетания не
    # идёт: иначе `ISO 9001` приедет и как непереводимое, и как «термин
    # ISO», и человеку придётся решать одно и то же дважды.
    taken = set(abbreviations) | set(standards)

    phrases = _phrases(chunks, min_frequency=min_frequency, taken=taken)

    candidates = [
        *_to_candidates(abbreviations, GlossaryEntryKind.ABBREVIATION, min_frequency),
        *_to_candidates(standards, GlossaryEntryKind.DO_NOT_TRANSLATE, min_frequency),
        *phrases,
    ]

    # Сортировка не косметика: список из четырёхсот строк человек разбирает
    # сверху вниз и до конца доходит не всегда, поэтому наверху должно
    # стоять то, что чаще всего испортит перевод.
    candidates.sort(key=lambda item: (-item.score, -item.frequency, item.source.casefold()))

    return candidates[:limit]


def _to_candidates(
    found: dict[str, _Sighting], kind: GlossaryEntryKind, min_frequency: int
) -> list[Candidate]:
    """Собранные вхождения — в кандидаты.

    Аббревиатуры и стандарты проходят с частотой единица, в отличие от
    словосочетаний: `ГОСТ Р 52931`, упомянутый один раз, всё равно обязан
    попасть в перевод дословно, а однократное сочетание слов термином, как
    правило, не является.
    """
    threshold = 1 if kind is not GlossaryEntryKind.TERM else min_frequency

    return [
        Candidate(
            source=sighting.surfaces.most_common(1)[0][0],
            kind=kind,
            frequency=sighting.count,
            sample=sighting.sample,
            expansion=sighting.expansion,
            first_index=sighting.first_index,
            # Аббревиатуры и стандарты идут выше словосочетаний той же
            # частоты: ошибка в них заметнее и правится дороже.
            score=sighting.count * 2.5,
        )
        for sighting in found.values()
        if sighting.count >= threshold
    ]


def _abbreviations(chunks: Sequence[_Chunk]) -> dict[str, _Sighting]:
    """Аббревиатуры с расшифровкой, если она есть в тексте."""
    any_case, exact_case = _word_counts(chunks)
    found: dict[str, _Sighting] = {}

    for index, text in chunks:
        # Обозначения стандартов разбираются отдельно и целиком. Без этого
        # `EN 60204-1` дал бы ещё и кандидата `EN`, и человеку пришлось бы
        # решать судьбу половины обозначения.
        designations = [match.span() for match in _STANDARD.finditer(text)]

        for match in _ABBREVIATION.finditer(text):
            word = match.group()

            if _ROMAN.match(word):
                continue

            if any(left <= match.start() and match.end() <= right for left, right in designations):
                continue

            key = word.casefold()

            # Слово, которое чаще пишут не заглавными, аббревиатурой не
            # является: `WARNING` в шапке главы — это тот же `warning` из
            # текста, набранный капслоком, и в словарь ему не надо.
            if (any_case[key] - exact_case[word]) * 2 > any_case[key]:
                continue

            sighting = found.setdefault(key, _Sighting())
            sighting.count += 1
            sighting.surfaces[word] += 1

            if not sighting.sample:
                sighting.sample = _sample(text, match.start(), match.end())
                sighting.first_index = index

            if sighting.expansion is None:
                sighting.expansion = _expansion(text, match.start(), match.end(), word)

    return found


def _word_counts(chunks: Sequence[_Chunk]) -> tuple[Counter[str], Counter[str]]:
    """Частоты слов: без учёта регистра и по точному написанию.

    Считаются одним проходом на весь документ, а не по слову: подсчёт
    вхождений отдельным поиском для каждого кандидата превращает разбор
    книги в квадрат от числа слов.
    """
    any_case: Counter[str] = Counter()
    exact_case: Counter[str] = Counter()

    for _, text in chunks:
        for match in _TOKEN.finditer(text):
            word = match.group()
            any_case[word.casefold()] += 1
            exact_case[word] += 1

    return any_case, exact_case


def _standards(chunks: Sequence[_Chunk]) -> dict[str, _Sighting]:
    found: dict[str, _Sighting] = {}

    for index, text in chunks:
        for match in _STANDARD.finditer(text):
            # Неразрывный пробел внутри обозначения приводится к обычному:
            # иначе `ISO 9001` и `ISO 9001` станут двумя записями.
            word = re.sub(r"[\s ]+", " ", match.group()).strip()
            key = word.casefold()

            sighting = found.setdefault(key, _Sighting())
            sighting.count += 1
            sighting.surfaces[word] += 1

            if not sighting.sample:
                sighting.sample = _sample(text, match.start(), match.end())
                sighting.first_index = index

    return found


def _phrases(chunks: Sequence[_Chunk], *, min_frequency: int, taken: set[str]) -> list[Candidate]:
    """Словосочетания и одиночные слова по частоте, с поправкой на вложенность."""
    # Сочетание не может встретиться чаще, чем самое редкое слово в нём.
    # Поэтому сначала считаем слова и дальше не строим сочетаний со словами,
    # встретившимися реже порога. Отсев точный, а не приблизительный, и
    # снимает с книги основную массу: одиночных слов в тексте больше всего.
    frequent = {word for word, count in _word_counts(chunks)[0].items() if count >= min_frequency}

    sightings: dict[tuple[str, ...], _Sighting] = {}

    for index, text in chunks:
        for window in _windows(text):
            for size in range(1, MAX_TERM_WORDS + 1):
                for start in range(0, len(window) - size + 1):
                    part = window[start : start + size]
                    key = tuple(token.group().casefold() for token in part)

                    if not _is_termlike(key) or any(word not in frequent for word in key):
                        continue

                    surface = _collapse(text[part[0].start() : part[-1].end()])
                    sighting = sightings.setdefault(key, _Sighting())
                    sighting.count += 1
                    sighting.surfaces[surface] += 1

                    if not sighting.sample:
                        sighting.sample = _sample(text, part[0].start(), part[-1].end())
                        sighting.first_index = index

    return _independent(sightings, min_frequency=min_frequency, taken=taken)


def _independent(
    sightings: dict[tuple[str, ...], _Sighting], *, min_frequency: int, taken: set[str]
) -> list[Candidate]:
    """Отсеять сочетания, которые существуют только внутри более длинных.

    `valve` двенадцать раз и `check valve` десять раз — это не два термина
    равного веса: самостоятельных вхождений у короткого всего два. Считаем
    от длинных к коротким и вычитаем у короткого то, что уже учтено
    длинным, иначе список возглавят обрывки настоящих терминов.
    """
    nested: Counter[tuple[str, ...]] = Counter()
    candidates: list[Candidate] = []

    for key in sorted(sightings, key=len, reverse=True):
        sighting = sightings[key]
        independent = sighting.count - nested[key]

        if independent < min_frequency:
            continue

        surface = sighting.surfaces.most_common(1)[0][0]

        if surface.casefold() in taken:
            continue

        candidates.append(
            Candidate(
                source=surface,
                kind=GlossaryEntryKind.TERM,
                frequency=independent,
                sample=sighting.sample,
                first_index=sighting.first_index,
                # Многословное ценнее односложного той же частоты: именно
                # на сочетаниях модель придумывает свой вариант, а `check
                # valve` — это «обратный клапан», а не «проверьте клапан».
                score=independent * (1.0 + math.log2(len(key) + 1)),
            )
        )

        for size in range(1, len(key)):
            for start in range(0, len(key) - size + 1):
                nested[key[start : start + size]] += sighting.count

    return candidates


def _windows(text: str) -> list[list[re.Match[str]]]:
    """Цепочки слов, не разорванные знаками препинания.

    Через запятую и точку словосочетания не тянутся: «клапан, насос» — это
    два термина, а не один. Разделителем считается всё, кроме пробелов
    между словами.
    """
    windows: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = []
    previous: re.Match[str] | None = None

    for match in _TOKEN.finditer(text):
        if previous is not None and text[previous.end() : match.start()].strip():
            windows.append(current)
            current = []

        current.append(match)
        previous = match

    if current:
        windows.append(current)

    return windows


def _is_termlike(key: tuple[str, ...]) -> bool:
    """Похоже ли сочетание на термин, а не на обрывок фразы."""
    if key[0] in _STOPWORDS or key[-1] in _STOPWORDS:
        return False

    # Односимвольные слова — это инициалы, обозначения осей и мусор разбора.
    return all(len(word) > 1 for word in key)


def _collapse(text: str) -> str:
    """Свернуть пробелы: перенос строки внутри сочетания — не часть термина."""
    return re.sub(r"\s+", " ", text).strip()


def _sample(text: str, start: int, end: int) -> str:
    """Кусок текста вокруг вхождения — чтобы решать не по голому списку."""
    left = max(0, start - SAMPLE_RADIUS)
    right = min(len(text), end + SAMPLE_RADIUS)

    fragment = text[left:right].strip()

    if left > 0:
        fragment = "… " + fragment
    if right < len(text):
        fragment = fragment + " …"

    return re.sub(r"\s+", " ", fragment)


def _expansion(text: str, start: int, end: int, abbreviation: str) -> str | None:
    """Расшифровка аббревиатуры, если автор дал её рядом.

    Две формы, обе распространённые: `Programmable Logic Controller (PLC)`
    и `ПЛК (программируемый логический контроллер)`. Расшифровка проверяется
    по первым буквам — совпадение случайным не бывает, а без проверки в
    поле уехал бы кусок соседнего предложения.
    """
    letters = [char for char in abbreviation.casefold() if char.isalpha()]
    if not letters:
        return None

    in_parentheses = text[max(0, start - 1) : start] == "(" and text[end : end + 1] == ")"

    if in_parentheses:
        before = text[: max(0, start - 1)]
        words = [match.group() for match in _TOKEN.finditer(before)]

        # Ищем от точного числа слов вверх: служебные слова внутри
        # расшифровки («degree of protection») инициалов не дают.
        for size in range(len(letters), len(letters) + 3):
            if size > len(words):
                break

            tail = words[-size:]
            if _initials_match(tail, letters):
                return " ".join(tail)

        return None

    after = text[end:]
    match = re.match(r"\s*\(([^)]{2,200})\)", after)

    if match is None:
        return None

    words = [token.group() for token in _TOKEN.finditer(match.group(1))]

    return " ".join(words) if _initials_match(words, letters) else None


def _initials_match(words: Sequence[str], letters: Sequence[str]) -> bool:
    """Складываются ли первые буквы слов в аббревиатуру."""
    initials = [word[0].casefold() for word in words if word.casefold() not in _STOPWORDS]

    return initials == list(letters)
