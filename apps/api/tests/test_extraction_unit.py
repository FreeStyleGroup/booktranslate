"""Извлечение терминов из текста.

Без базы: извлечение — чистая логика, и цена ошибки в ней высокая. Список
кандидатов человек разбирает руками, поэтому шум в нём стоит рабочего
времени, а пропущенный термин — расхождения в переводе, которое заметит
уже читатель.
"""

from app.models.memory import GlossaryEntryKind
from app.services.extraction import Candidate, extract


def sources(candidates: list[Candidate]) -> list[str]:
    return [item.source for item in candidates]


def find(candidates: list[Candidate], source: str) -> Candidate:
    match = [item for item in candidates if item.source.casefold() == source.casefold()]
    assert match, f"{source} не найден среди {sources(candidates)}"

    return match[0]


def test_repeated_phrase_becomes_candidate() -> None:
    found = extract(
        [
            "Open the check valve before start.",
            "The check valve must be closed.",
            "Inspect the check valve every month.",
        ]
    )

    assert find(found, "check valve").frequency == 3


def test_nested_word_does_not_compete_with_phrase() -> None:
    """«valve» встречается только внутри «check valve» — отдельным термином он не является."""
    found = extract(
        [
            "Open the check valve before start.",
            "The check valve must be closed.",
            "Inspect the check valve every month.",
        ]
    )

    assert "valve" not in [item.source.casefold() for item in found]


def test_word_with_own_occurrences_survives() -> None:
    """А если слово живёт и само по себе, оно остаётся кандидатом."""
    found = extract(
        [
            "Open the check valve before start.",
            "The check valve must be closed.",
            "Every valve has a label.",
            "The valve is heavy.",
        ]
    )

    assert find(found, "valve").frequency == 2


def test_phrase_outranks_single_word() -> None:
    """Сочетание ценнее одиночного слова той же частоты: на нём и ошибаются."""
    found = extract(
        [
            "The pressure gauge shows the value.",
            "The pressure gauge is broken.",
            "Replace the pressure gauge.",
            "The manual describes the gauge and the pump.",
            "The pump and the gauge are separate.",
        ]
    )

    order = [item.source.casefold() for item in found]

    assert order.index("pressure gauge") < order.index("pump")


def test_stopwords_do_not_start_or_end_a_term() -> None:
    found = extract(
        [
            "The valve of the pump is closed.",
            "The valve of the pump is open.",
            "Check the valve of the pump.",
        ]
    )

    for item in found:
        assert not item.source.casefold().startswith("the ")
        assert not item.source.casefold().endswith(" the")
        assert not item.source.casefold().endswith(" of")


def test_single_occurrence_is_not_a_term() -> None:
    found = extract(["The hydraulic accumulator is mounted on the frame."])

    assert "hydraulic accumulator" not in [item.source.casefold() for item in found]


def test_abbreviation_keeps_its_expansion() -> None:
    found = extract(
        [
            "The Programmable Logic Controller (PLC) runs the cycle.",
            "Replace the PLC module.",
            "PLC settings are stored in memory.",
        ]
    )

    plc = find(found, "PLC")

    assert plc.kind is GlossaryEntryKind.ABBREVIATION
    assert plc.expansion == "Programmable Logic Controller"


def test_abbreviation_expansion_after_the_short_form() -> None:
    """Русская запись даёт расшифровку в скобках после аббревиатуры."""
    found = extract(
        [
            "ПЛК (программируемый логический контроллер) управляет циклом.",
            "Настройки ПЛК хранятся в памяти.",
        ]
    )

    assert find(found, "ПЛК").expansion == "программируемый логический контроллер"


def test_unrelated_parentheses_are_not_taken_for_expansion() -> None:
    """В скобках рядом может стоять что угодно — сходятся только инициалы."""
    found = extract(
        [
            "The PLC (see chapter four) runs the cycle.",
            "Replace the PLC module.",
        ]
    )

    assert find(found, "PLC").expansion is None


def test_shouted_word_is_not_an_abbreviation() -> None:
    """`WARNING` в шапке главы — то же слово капслоком, а не аббревиатура."""
    found = extract(
        [
            "WARNING",
            "A warning is printed on the cover.",
            "Read the warning before start.",
            "The warning stays visible.",
        ]
    )

    assert "WARNING" not in sources(found)


def test_roman_numeral_is_not_an_abbreviation() -> None:
    found = extract(
        [
            "Chapter II describes the pump.",
            "Chapter II ends with a table.",
        ]
    )

    assert "II" not in sources(found)


def test_standard_designation_is_not_translated() -> None:
    found = extract(["The machine complies with ISO 9001 and EN 60204-1."])

    assert find(found, "ISO 9001").kind is GlossaryEntryKind.DO_NOT_TRANSLATE
    assert find(found, "EN 60204-1").kind is GlossaryEntryKind.DO_NOT_TRANSLATE


def test_standard_prefix_is_not_a_separate_candidate() -> None:
    """`EN 60204-1` — одно обозначение; отдельный кандидат `EN` человеку не нужен."""
    found = extract(["The machine complies with EN 60204-1 only."])

    assert "EN" not in sources(found)
    assert "EN 60204-1" in sources(found)


def test_gost_designation_is_recognised() -> None:
    found = extract(["Прибор соответствует ГОСТ Р 52931-2008."])

    assert find(found, "ГОСТ Р 52931-2008").kind is GlossaryEntryKind.DO_NOT_TRANSLATE


def test_russian_phrase_is_extracted() -> None:
    found = extract(
        [
            "Обратный клапан установлен на входе.",
            "Обратный клапан следует проверять раз в месяц.",
            "Замените обратный клапан при износе.",
        ]
    )

    assert find(found, "обратный клапан").frequency == 3


def test_sample_shows_the_term_in_context() -> None:
    found = extract(
        [
            "Open the check valve before start.",
            "The check valve must be closed.",
        ]
    )

    assert "check valve" in find(found, "check valve").sample


def test_limit_caps_the_list() -> None:
    texts = [f"Deck plate number {index} holds the deck plate frame." for index in range(50)]

    assert len(extract(texts, limit=3)) == 3
