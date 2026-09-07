"""Проверки перевода.

Без базы. Здесь важнее обычного, чтобы проверка не поднимала ложную
тревогу: список находок, в котором половина мусора, редактор перестаёт
читать через день, и вместе с мусором перестаёт видеть настоящие ошибки.
"""

from app.models.memory import GlossaryEntryKind
from app.models.segment import SegmentKind
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
        expand_on_first_use=bool(kwargs.get("expand_on_first_use", False)),
    )


def run(source: str, target: str, *, terms: list[Term] | None = None) -> list[str]:
    findings = checks.run_checks(
        source, target, glossary=Glossary(terms or []), kind=SegmentKind.PARAGRAPH
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


def test_untranslated_segment_is_reported() -> None:
    text = "The pressure relief valve must be inspected every month."

    assert "untranslated" in run(text, text)


def test_short_identical_string_is_not_untranslated() -> None:
    """«230 V» и «max» законно совпадают в обоих языках."""
    assert run("230 V max", "230 V max") == []


def test_code_is_allowed_to_stay_the_same() -> None:
    text = "systemctl restart application.service --now"

    findings = checks.run_checks(text, text, glossary=Glossary([]), kind=SegmentKind.CODE)

    assert [item.check for item in findings] == []


def test_empty_translation_is_reported_alone() -> None:
    """Пустой перевод — это отсутствие перевода; остальные придирки к нему бессмысленны."""
    findings = checks.run_checks(
        "Tighten to 45 Nm.", "   ", glossary=Glossary([]), kind=SegmentKind.PARAGRAPH
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


def test_score_puts_worse_segment_first() -> None:
    bad = checks.run_checks(
        "Tighten to 45 Nm.", "   ", glossary=Glossary([]), kind=SegmentKind.PARAGRAPH
    )
    mild = checks.run_checks(
        "Open the valve.",
        "Откройте вентиль.",
        glossary=Glossary([term("valve", "клапан")]),
        kind=SegmentKind.PARAGRAPH,
    )

    assert checks.score(bad) < checks.score(mild) < 1.0


def test_clean_segment_has_no_verdict() -> None:
    assert checks.as_json([]) is None


def test_verdict_carries_findings_and_score() -> None:
    findings = checks.run_checks(
        "Tighten to 45 Nm.",
        "Затянуть моментом 40 Н·м.",
        glossary=Glossary([]),
        kind=SegmentKind.PARAGRAPH,
    )

    verdict = checks.as_json(findings)

    assert verdict is not None
    assert verdict["score"] < 1.0
    assert verdict["findings"][0]["check"] == "numbers"


def test_first_use_requires_the_abbreviation() -> None:
    abbreviation = term("MM", "маркет-мейкер", expand_on_first_use=True)

    assert checks.first_use_finding(abbreviation, "Маркет-мейкер котирует цены.") is not None
    assert (
        checks.first_use_finding(abbreviation, "Маркет-мейкер (market maker, MM) котирует цены.")
        is None
    )
