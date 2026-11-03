"""Проверки перевода.

Без базы. Здесь важнее обычного, чтобы проверка не поднимала ложную
тревогу: список находок, в котором половина мусора, редактор перестаёт
читать через день, и вместе с мусором перестаёт видеть настоящие ошибки.
"""

from app.models.block import BlockKind
from app.models.memory import FirstUseRule, GlossaryEntryKind
from app.services import checks
from app.services.glossary import Glossary, Term


def term(source: str, target: str, **kwargs: object) -> Term:
    return Term(
        source=source,
        target=target,
        mandatory=bool(kwargs.get("mandatory", True)),
        note=None,
        kind=kwargs.get("kind", GlossaryEntryKind.TERM),  # type: ignore[arg-type]
        case_sensitive=bool(kwargs.get("case_sensitive", False)),
        settled=bool(kwargs.get("settled", True)),
        first_use_rule=kwargs.get("first_use_rule", FirstUseRule.NONE),  # type: ignore[arg-type]
    )


def run(source: str, target: str, *, terms: list[Term] | None = None) -> list[str]:
    findings = checks.run_checks(
        source, target, glossary=Glossary(terms or []), kind=BlockKind.PARAGRAPH
    )

    return [finding.check for finding in findings]


def test_lost_number_is_reported() -> None:
    assert "numbers" in run("Tighten to 45 Nm.", "Затянуть моментом 40 Н·м.")


def test_invented_number_is_reported() -> None:
    """Придуманное число опаснее пропавшего: его не с чем сверить в тексте."""
    assert "numbers" in run("Tighten the bolt.", "Затянуть болт моментом 45 Н·м.")


def test_matching_numbers_are_quiet() -> None:
    assert run("Tighten to 45 Nm.", "Затянуть моментом 45 Н·м.") == []


def test_decimal_comma_is_not_a_discrepancy() -> None:
    """`1.5` и `1,5` — одно число: в русском десятичный знак другой."""
    assert run("Clearance is 1.5 mm.", "Зазор 1,5 мм.") == []


def test_thousands_separator_is_not_a_discrepancy() -> None:
    assert run("Up to 1,250 rpm.", "До 1 250 об/мин.") == []


def test_trailing_zeros_do_not_matter() -> None:
    assert run("Set 2.50 bar.", "Установить 2,5 бар.") == []


def test_lost_placeholder_is_reported() -> None:
    """Потерянный `{0}` — это пустое место на экране вместо значения."""
    assert "placeholders" in run("Replace {part} now.", "Замените деталь немедленно.")


def test_lost_tag_is_reported() -> None:
    assert "placeholders" in run("Press <b>Start</b> now.", "Нажмите Пуск немедленно.")


def test_untranslated_block_is_reported() -> None:
    text = "The pressure relief valve must be inspected every month."

    assert "untranslated" in run(text, text)


def test_short_identical_string_is_not_untranslated() -> None:
    """«230 V» и «max» законно совпадают в обоих языках."""
    assert run("230 V max", "230 V max") == []


def test_code_is_allowed_to_stay_the_same() -> None:
    text = "systemctl restart application.service --now"

    findings = checks.run_checks(text, text, glossary=Glossary([]), kind=BlockKind.CODE)

    assert [item.check for item in findings] == []


def test_empty_translation_is_reported_alone() -> None:
    """Пустой перевод — это отсутствие перевода; остальные придирки к нему бессмысленны."""
    findings = checks.run_checks(
        "Tighten to 45 Nm.", "   ", glossary=Glossary([]), kind=BlockKind.PARAGRAPH
    )

    assert [item.check for item in findings] == ["empty"]


def test_missing_term_is_reported() -> None:
    checks_found = run("Open the valve.", "Откройте вентиль.", terms=[term("valve", "клапан")])

    assert "glossary" in checks_found


def test_unsettled_term_is_quiet() -> None:
    """Спор о словаре не должен выглядеть как ошибка перевода."""
    checks_found = run(
        "Open the valve.",
        "Откройте вентиль.",
        terms=[term("valve", "клапан", settled=False)],
    )

    assert checks_found == []


def test_first_use_requires_the_abbreviation() -> None:
    abbreviation = term("MM", "маркет-мейкер", first_use_rule=FirstUseRule.EXPAND)

    assert checks.first_use_finding(abbreviation, "Маркет-мейкер котирует цены.") is not None
    assert (
        checks.first_use_finding(abbreviation, "Маркет-мейкер (market maker, MM) котирует цены.")
        is None
    )


def findings(
    source: str,
    target: str,
    *,
    kind: BlockKind = BlockKind.PARAGRAPH,
    terms: list[Term] | None = None,
    protected: tuple[str, ...] = (),
) -> list[checks.Finding]:
    return checks.run_checks(
        source, target, glossary=Glossary(terms or []), kind=kind, protected=protected
    )


def names(source: str, target: str, **kwargs: object) -> list[str]:
    return [item.check for item in findings(source, target, **kwargs)]  # type: ignore[arg-type]


def test_lost_minus_is_reported_as_a_sign() -> None:
    assert names("Keep below -40 °C.", "Держите ниже 40 °C.") == ["signs"]


def test_minus_in_any_form_is_quiet() -> None:
    assert names("Keep below -40 °C.", "Держите ниже −40 °C.") == []
    assert names("Keep below -40 °C.", "Держите ниже минус 40 °C.") == []


def test_hyphen_in_a_name_is_not_a_sign() -> None:
    assert names("The CH-47 uses 5 bar.", "В CH-47 применяется 5 бар.") == []


def test_invented_sign_is_reported() -> None:
    assert names("Offset 5 mm.", "Смещение -5 мм.") == ["signs"]


def test_range_written_differently_is_quiet() -> None:
    assert names("Use 5-10 bar.", "Используйте 5–10 бар.") == []
    assert names("Use 5 to 10 bar.", "Используйте от 5 до 10 бар.") == []


def test_range_that_stopped_being_a_range_is_reported() -> None:
    assert names("Use 5-10 bar.", "Используйте 5 и 10 бар.") == ["ranges"]


def test_reversed_range_is_reported() -> None:
    assert "ranges" in names("Use 5-10 bar.", "Используйте 10-5 бар.")


def test_unit_in_any_legal_form_is_quiet() -> None:
    assert names("Length 5 mm.", "Длина 5 мм.") == []
    assert names("Length 5 mm.", "Длина 5 миллиметров.") == []
    assert names("Up to 1,250 rpm.", "До 1 250 об/мин.") == []


def test_wrong_unit_is_reported() -> None:
    assert names("Length 5 mm.", "Длина 5 см.") == ["units"]
    assert names("Supply 230 V.", "Питание 230 А.") == ["units"]


def test_lost_number_does_not_also_complain_about_its_unit() -> None:
    """Одна причина — одна находка: иначе список растёт, а знания в нём не прибавляется."""
    assert names("Length 5 mm.", "Длина 7 мм.") == ["numbers", "numbers"]


def test_name_from_code_must_stay() -> None:
    assert names("Set max_speed now.", "Задайте maxSpeed сейчас.") == ["variables"]
    assert names("Call getValue() first.", "Сначала вызовите getValue().") == []
    assert names("Set CONFIG_PATH now.", "Задайте CONFIG_PATH сейчас.") == []


def test_reference_survives_in_russian_cases() -> None:
    assert names("See Figure 3.1 and Table 2.", "См. рисунок 3.1 и табл. 2.") == []
    assert names("See Figure 3.1.", "На рис. 3.1 показано.") == []
    assert names("In Section 4.2.", "В разделе 4.2.") == []
    assert names("See Appendix B.", "См. Приложение Б.") == []


def test_reference_to_another_object_is_reported() -> None:
    assert names("See Figure 3.", "См. таблицу 3.") == ["cross_references"]


def test_plain_word_after_table_is_not_a_reference() -> None:
    """«Таблица с данными»: строчная буква после слова — это не метка."""
    assert names("таблица с данными важна", "the table with data matters") == []


def test_placeholder_left_in_text_is_critical() -> None:
    [finding] = findings("Radius is set.", "Радиус ⟦1⟧ задан.")

    assert finding.check == "object_placeholders"
    assert finding.severity.value == "critical"


def test_lost_protected_span_is_reported() -> None:
    assert names("Radius r2 is set.", "Радиус задан.", protected=("r2",)) == [
        "numbers",
        "object_placeholders",
    ]
    assert names("Radius r2 is set.", "Радиус r2 задан.", protected=("r2",)) == []


def test_changed_listing_is_critical_and_nothing_else_is_compared() -> None:
    [finding] = findings("open(relief)  ", "open(relief)", kind=BlockKind.CODE)

    assert finding.check == "code_changed"
    assert finding.severity.value == "critical"


def test_list_number_must_stay() -> None:
    item = BlockKind.LIST_ITEM

    assert names("1. Open the valve.", "1. Откройте клапан.", kind=item) == []
    assert names("1. Open the valve.", "Откройте клапан.", kind=item) == [
        "numbers",
        "list_numbering",
    ]
    assert names("(i) Open it.", "(ii) Откройте.", kind=item) == ["list_numbering"]


def test_localized_list_letter_does_not_need_registration() -> None:
    [finding] = findings("a) Open it.", "а) Откройте.", kind=BlockKind.LIST_ITEM)

    assert finding.check == "list_numbering"
    assert finding.not_required == checks.LOCALIZED_MARKER


def test_optional_term_is_a_hint_that_does_not_need_registration() -> None:
    [finding] = findings(
        "Open the valve.", "Откройте вентиль.", terms=[term("valve", "клапан", mandatory=False)]
    )

    assert finding.not_required == checks.OPTIONAL_TERM


def test_mandatory_term_needs_registration() -> None:
    [finding] = findings("Open the valve.", "Откройте вентиль.", terms=[term("valve", "клапан")])

    assert finding.not_required is None
    assert finding.category.value == "terminology"


def test_every_finding_has_severity_and_category() -> None:
    found = findings("Use -5 to 10 bar, see Figure 3.", "Используйте 7.", kind=BlockKind.PARAGRAPH)

    assert found
    assert all(item.severity is not None and item.category is not None for item in found)


def test_first_use_goes_through_the_same_check() -> None:
    ruled = term("MM", "маркет-мейкер", first_use_rule=FirstUseRule.EXPAND)

    found = checks.run_checks(
        "The MM quotes.",
        "Маркет-мейкер даёт цену.",
        glossary=Glossary([]),
        kind=BlockKind.PARAGRAPH,
        first_use=[ruled],
    )

    assert [item.check for item in found] == ["first_use"]
