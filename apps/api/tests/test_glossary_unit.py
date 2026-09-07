"""Сопоставление глоссария с текстом.

Без базы: сопоставление — чистая логика, и именно в ней прячутся ошибки,
из-за которых модель получает требования, которых в тексте нет.
"""

from app.models.memory import GlossaryEntryKind
from app.services.glossary import Glossary, Term


def term(source: str, target: str, **kwargs: object) -> Term:
    return Term(
        source=source,
        target=target,
        mandatory=bool(kwargs.get("mandatory", True)),
        note=None,
        kind=kwargs.get("kind", GlossaryEntryKind.TERM),  # type: ignore[arg-type]
        case_sensitive=bool(kwargs.get("case_sensitive", False)),
    )


def test_match_respects_word_boundaries() -> None:
    """«air» не должен находиться внутри «repair»."""
    glossary = Glossary([term("air", "воздух")])

    assert glossary.match("Check the air filter") == [term("air", "воздух")]
    assert glossary.match("Send it to repair") == []


def test_longer_term_comes_first() -> None:
    """Есть и «клапан», и «обратный клапан» — в подсказку идёт точный."""
    glossary = Glossary([term("valve", "клапан"), term("check valve", "обратный клапан")])

    matched = glossary.match("Replace the check valve")

    assert matched[0].source == "check valve"


def test_case_insensitive_by_default() -> None:
    glossary = Glossary([term("valve", "клапан")])

    assert glossary.match("VALVE is closed")


def test_abbreviation_is_case_sensitive() -> None:
    """«ИТ» без учёта регистра нашлось бы где угодно."""
    glossary = Glossary(
        [term("ИТ", "IT", kind=GlossaryEntryKind.ABBREVIATION, case_sensitive=True)]
    )

    assert glossary.match("Отдел ИТ отвечает за сеть")
    assert not glossary.match("Он ит так делает")


def test_missing_term_is_reported() -> None:
    glossary = Glossary([term("valve", "клапан")])

    missing = glossary.missing_in("Open the valve", "Откройте вентиль")

    assert [item.target for item in missing] == ["клапан"]


def test_inflected_form_counts_as_used() -> None:
    """Русский флективный: «клапана» — это тот же «клапан»."""
    glossary = Glossary([term("valve", "клапан")])

    assert glossary.missing_in("Open the valve", "Не открывайте клапана") == []


def test_recommended_term_does_not_flag() -> None:
    glossary = Glossary([term("valve", "клапан", mandatory=False)])

    assert glossary.missing_in("Open the valve", "Откройте вентиль") == []


def test_do_not_translate_requires_exact_form() -> None:
    """«USB», превратившийся в «Usb», — это ошибка, а не падеж."""
    glossary = Glossary(
        [term("USB", "USB", kind=GlossaryEntryKind.DO_NOT_TRANSLATE, case_sensitive=True)]
    )

    assert glossary.missing_in("Connect the USB cable", "Подключите кабель USB") == []
    assert glossary.missing_in("Connect the USB cable", "Подключите кабель Usb")
