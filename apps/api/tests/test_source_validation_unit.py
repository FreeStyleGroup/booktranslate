"""Проверка исходника: чтение фактов из файла и сличение изданий.

Без базы и без FastAPI: `read_facts` принимает путь и формат,
`describe_mismatch` — две записи проверки. Так их можно гонять на
настоящих файлах, а не на моках.
"""

from pathlib import Path

from app.models.book import SourceValidationResult
from app.models.document import SourceFormat
from app.services.source_validation import describe_mismatch, read_facts


def validation(*, title: str | None = None, author: str | None = None) -> SourceValidationResult:
    """Запись проверки в памяти: для сличения нужны только метаданные."""
    return SourceValidationResult(
        format_ok=True,
        has_text_layer=True,
        parser_version="test",
        warnings=[],
        meta_title=title,
        meta_author=author,
    )


def test_text_file_is_readable(tmp_path: Path) -> None:
    path = tmp_path / "manual.txt"
    path.write_text("Руководство по эксплуатации.\n\nПервый раздел.", encoding="utf-8")

    facts = read_facts(path, SourceFormat.TXT)

    assert facts.format_ok
    assert facts.has_text_layer
    assert facts.warnings == ()
    # У простого текста объявленных сведений нет: название в нём — первая
    # строка, а это догадка, а не метаданные.
    assert facts.title is None


def test_empty_file_says_there_is_no_text(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("   \n\n", encoding="utf-8")

    facts = read_facts(path, SourceFormat.TXT)

    assert facts.format_ok
    assert not facts.has_text_layer
    assert facts.warnings


def test_unsupported_format_is_honest(tmp_path: Path) -> None:
    """XLIFF не разбирается — и проверка говорит это прямо, а не падает."""
    path = tmp_path / "strings.xlf"
    path.write_bytes(b"<xliff/>")

    facts = read_facts(path, SourceFormat.XLIFF)

    assert not facts.format_ok
    assert not facts.has_text_layer
    assert facts.warnings


def test_different_titles_warn_about_editions() -> None:
    mismatch = describe_mismatch(
        validation(title="Machine Learning for Asset Managers"),
        validation(title="Advances in Financial Machine Learning"),
    )

    assert mismatch is not None
    assert "по-разному" in mismatch


def test_subtitle_is_not_a_mismatch() -> None:
    """Подзаголовок и серия у одного издания обычны — это не расхождение."""
    mismatch = describe_mismatch(
        validation(title="Machine Learning"),
        validation(title="Machine Learning: A Practical Guide"),
    )

    assert mismatch is None


def test_punctuation_and_case_are_not_a_mismatch() -> None:
    mismatch = describe_mismatch(
        validation(title="Машинное обучение: руководство"),
        validation(title="МАШИННОЕ ОБУЧЕНИЕ — РУКОВОДСТВО"),
    )

    assert mismatch is None


def test_missing_metadata_is_not_a_mismatch() -> None:
    """Отсутствие сведений — это их отсутствие, а не расхождение."""
    assert describe_mismatch(validation(title="Машинное обучение"), validation()) is None
    assert describe_mismatch(validation(), validation()) is None


def test_different_authors_warn() -> None:
    mismatch = describe_mismatch(
        validation(title="Машинное обучение", author="Маркос Лопес де Прадо"),
        validation(title="Машинное обучение", author="Эндрю Ын"),
    )

    assert mismatch is not None
    assert "авторы" in mismatch
