"""Снимок версии глоссария: сумма, отличия обязательных терминов, затронутые блоки."""

import uuid
from dataclasses import replace

import pytest

from app.models.glossary_version import TermChangeKind
from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTermStatus
from app.services.errors import InvalidInputError
from app.services.glossary import Glossary, Term, clean_variants
from app.services.term_impact import Entry, TextBlock, affected, checksum, diff


def entry(source: str, target: str, **changes: object) -> Entry:
    base = Entry(
        source_term=source,
        source_term_normalized=source.casefold(),
        target_term=target,
        allowed_variants=(),
        kind=GlossaryEntryKind.TERM,
        status=GlossaryTermStatus.CONFIRMED,
        mandatory=True,
        case_sensitive=False,
        first_use_rule=FirstUseRule.NONE,
        domain=None,
        note=None,
        reference=None,
    )

    return replace(base, **changes)  # type: ignore[arg-type]


VALVE = entry("relief valve", "предохранительный клапан")
PUMP = entry("pump", "насос")


def test_checksum_does_not_depend_on_reading_order() -> None:
    assert checksum([VALVE, PUMP]) == checksum([PUMP, VALVE])
    assert checksum([VALVE, PUMP]) != checksum([VALVE, replace(PUMP, target_term="помпа")])
    # Пустая версия — тоже снимок, и сумма у неё своя.
    assert checksum([]) != checksum([VALVE])


def test_diff_lists_only_requirement_changes_of_mandatory_terms() -> None:
    before = [
        VALVE,
        PUMP,
        entry("rotor", "ротор"),
        entry("stator", "статор", mandatory=False),
        entry("seal", "уплотнение"),
    ]
    after = [
        # Перевод сменился — изменение.
        replace(VALVE, target_term="клапан сброса"),
        # Сменилось только примечание — для перевода ничего не изменилось.
        replace(PUMP, note="центробежный"),
        # Перестал быть обязательным — для перевода снят.
        entry("rotor", "ротор", mandatory=False),
        # Стал обязательным — появился.
        entry("stator", "статор"),
        # Новый необязательный — подсказка модели, не требование.
        entry("bearing", "подшипник", mandatory=False),
        # Новый обязательный.
        entry("shaft", "вал"),
    ]

    changes = {change.entry.source_term: change.kind for change in diff(before, after)}

    assert changes == {
        "relief valve": TermChangeKind.CHANGED,
        "rotor": TermChangeKind.REMOVED,
        "stator": TermChangeKind.ADDED,
        "shaft": TermChangeKind.ADDED,
        "seal": TermChangeKind.REMOVED,
    }


def test_settling_a_term_is_a_change() -> None:
    """Неустоявшийся термин проверкой не требуется; подтверждённый — требуется."""
    proposed = replace(VALVE, status=GlossaryTermStatus.PROPOSED)

    (change,) = diff([proposed], [VALVE])

    assert change.kind is TermChangeKind.CHANGED
    assert change.before == proposed
    assert change.after == VALVE


def test_affected_blocks_contain_the_whole_word() -> None:
    blocks = [
        TextBlock(uuid.uuid4(), "Check the Relief Valve daily."),
        TextBlock(uuid.uuid4(), "The relief valves are spare parts."),
        TextBlock(uuid.uuid4(), "The pump runs."),
        TextBlock(uuid.uuid4(), "A sump is not a pump-room."),
    ]

    # Изменения идут по алфавиту терминов: сначала pump, потом relief valve.
    (pump_hits, valve_hits) = affected(blocks, diff([], [VALVE, PUMP]))

    assert valve_hits == [blocks[0].id]
    # «pump-room» — дефис граница слова, а «sump» — нет.
    assert pump_hits == [blocks[2].id, blocks[3].id]


def test_affected_follows_case_of_both_sides() -> None:
    plc = entry("PLC", "ПЛК", kind=GlossaryEntryKind.ABBREVIATION, case_sensitive=True)
    blocks = [TextBlock(uuid.uuid4(), "The PLC starts."), TextBlock(uuid.uuid4(), "Plc logs.")]

    # Регистр значим у обеих сторон — находится только точное написание.
    (strict,) = affected(blocks, diff([plc], [replace(plc, target_term="контроллер")]))
    assert strict == [blocks[0].id]

    # Значимость регистра сняли — затронуто всё, что находит любая сторона.
    (loose,) = affected(blocks, diff([plc], [replace(plc, case_sensitive=False)]))
    assert loose == [blocks[0].id, blocks[1].id]


def test_variants_are_cleaned_of_repeats_and_the_main_target() -> None:
    cleaned = clean_variants(
        ["клапан сброса", "  Клапан  сброса ", "", "предохранительный клапан", "КС"],
        target="Предохранительный клапан",
        kind=GlossaryEntryKind.TERM,
    )

    assert cleaned == ["клапан сброса", "КС"]


def test_do_not_translate_has_no_variants() -> None:
    with pytest.raises(InvalidInputError):
        clean_variants(["ЮСБ"], target="USB", kind=GlossaryEntryKind.DO_NOT_TRANSLATE)

    # Повтор основной формы — не вариант, а та же строка.
    assert clean_variants(["usb"], target="USB", kind=GlossaryEntryKind.DO_NOT_TRANSLATE) == []


def test_too_many_variants_are_refused() -> None:
    with pytest.raises(InvalidInputError):
        clean_variants(
            [f"вариант {number}" for number in range(21)],
            target="клапан",
            kind=GlossaryEntryKind.TERM,
        )


def test_allowed_variant_satisfies_the_glossary_check() -> None:
    glossary = Glossary(
        [
            Term(
                source="relief valve",
                target="предохранительный клапан",
                mandatory=True,
                note=None,
                allowed_variants=("клапан сброса",),
            )
        ]
    )

    assert glossary.missing_in("Open the relief valve.", "Откройте клапан сброса.") == []
    assert glossary.missing_in("Open the relief valve.", "Откройте вентиль.") != []
