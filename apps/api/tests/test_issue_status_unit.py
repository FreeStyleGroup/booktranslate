"""Таблица переходов и чистые части реестра: без базы."""

import csv
import io
import uuid
from datetime import UTC, datetime

import pytest
from openpyxl import load_workbook

from app.models.book_object import BookObject, ObjectType
from app.models.issue import Issue, IssueCategory, IssueSeverity, IssueStatus
from app.services.errors import ConflictError
from app.services.issue_attachments import clean_name, sniff
from app.services.issue_export import to_csv, to_xlsx
from app.services.issue_numbers import dedupe_key
from app.services.issue_status import DECIDED, OPEN, TRANSITIONS, can_transition, require_transition
from app.services.issues import IssueRow, priority_of

ALLOWED = {
    (IssueStatus.NEW, IssueStatus.CONFIRMED),
    (IssueStatus.NEW, IssueStatus.REJECTED),
    (IssueStatus.NEW, IssueStatus.NEEDS_CLARIFICATION),
    (IssueStatus.NEEDS_CLARIFICATION, IssueStatus.REOPENED),
    (IssueStatus.CONFIRMED, IssueStatus.FIXED),
    (IssueStatus.CONFIRMED, IssueStatus.REOPENED),
    (IssueStatus.FIXED, IssueStatus.VERIFIED),
    (IssueStatus.FIXED, IssueStatus.REOPENED),
    (IssueStatus.VERIFIED, IssueStatus.CLOSED),
    (IssueStatus.VERIFIED, IssueStatus.REOPENED),
    (IssueStatus.CLOSED, IssueStatus.REOPENED),
    (IssueStatus.REJECTED, IssueStatus.REOPENED),
    (IssueStatus.REOPENED, IssueStatus.CONFIRMED),
    (IssueStatus.REOPENED, IssueStatus.REJECTED),
    (IssueStatus.REOPENED, IssueStatus.NEEDS_CLARIFICATION),
}


@pytest.mark.parametrize("current", list(IssueStatus))
@pytest.mark.parametrize("target", list(IssueStatus))
def test_every_pair_of_states_is_decided_by_the_table(
    current: IssueStatus, target: IssueStatus
) -> None:
    assert can_transition(current, target) is ((current, target) in ALLOWED)


def test_every_state_is_in_the_table() -> None:
    assert set(TRANSITIONS) == set(IssueStatus)


def test_new_cannot_jump_to_fixed_and_closed_needs_verified() -> None:
    with pytest.raises(ConflictError):
        require_transition(IssueStatus.NEW, IssueStatus.FIXED)

    for source in IssueStatus:
        assert can_transition(source, IssueStatus.CLOSED) is (source is IssueStatus.VERIFIED)


def test_open_and_decided_split_every_state() -> None:
    assert {IssueStatus.CLOSED, IssueStatus.REJECTED} == DECIDED
    assert set(IssueStatus) == OPEN | DECIDED
    assert not OPEN & DECIDED


def test_priority_is_a_weight_where_severity_outranks_any_repetition() -> None:
    minor_everywhere = priority_of(IssueSeverity.MINOR, 10_000, None)
    major_everywhere = priority_of(IssueSeverity.MAJOR, 10_000, None)
    critical_once = priority_of(IssueSeverity.CRITICAL, 1, None)

    assert minor_everywhere < major_everywhere < critical_once


def test_risky_object_raises_priority() -> None:
    plain = priority_of(IssueSeverity.MAJOR, 1, None)
    formula = priority_of(IssueSeverity.MAJOR, 1, BookObject(type=ObjectType.EQUATION))

    assert formula > plain


def test_dedupe_key_ignores_spacing_and_case_but_not_the_revision() -> None:
    block = uuid.uuid4()
    revision = uuid.uuid4()

    def key(finding: str, *, on: uuid.UUID = revision) -> str:
        return dedupe_key(
            "numbers", block_id=block, object_id=None, revision_id=on, finding=finding
        )

    assert key("Число  12,5  пропало") == key("число 12,5 ПРОПАЛО")
    assert key("Число пропало") != key("Число пропало", on=uuid.uuid4())
    assert key("Число пропало") != key("Другое")


def test_only_real_snapshots_are_accepted() -> None:
    assert sniff(b"\x89PNG\r\n\x1a\n....") == ("image/png", ".png")
    assert sniff(b"\xff\xd8\xff\xe0....") == ("image/jpeg", ".jpg")
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("image/webp", ".webp")
    assert sniff(b"%PDF-1.7\n") == ("application/pdf", ".pdf")

    assert sniff(b"<svg xmlns='http://www.w3.org/2000/svg'><script>") is None
    assert sniff(b"<html><script>alert(1)</script>") is None
    assert sniff(b"MZ\x90\x00") is None


def test_shown_name_loses_path_and_control_characters() -> None:
    assert clean_name("../../etc/passwd", "снимок.png") == "passwd"
    assert clean_name("C:\\Users\\кто-то\\стр 12.png", "снимок.png") == "стр 12.png"
    assert clean_name("стр\r\nSet-Cookie: x.png", "снимок.png") == "стрSet-Cookie: x.png"
    assert clean_name("", "снимок.png") == "снимок.png"
    assert clean_name(None, "снимок.png") == "снимок.png"


def _row(description: str) -> IssueRow:
    issue = Issue(
        code="BK01-CH01-ERR-0001",
        category=IssueCategory.NUMBER,
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.NEW,
        priority_score=31,
        automatic=False,
        source_snapshot="=cmd|'/C calc'!A0",
        target_snapshot="+1+1",
        description=description,
        proposed_fix="@SUM(1)",
    )
    issue.created_at = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

    return IssueRow(
        issue=issue,
        book_title="-книга",
        block_code="CH01-B0001",
        object_code=None,
        detected_by="a@example.com",
        assignee=None,
    )


def test_csv_does_not_hand_formulas_to_a_spreadsheet() -> None:
    body = to_csv([_row('=HYPERLINK("http://evil")')])

    assert body.startswith(b"\xef\xbb\xbf")

    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    cells = rows[1]

    assert rows[0][0] == "Код"
    assert cells[0] == "BK01-CH01-ERR-0001"
    assert cells[1] == "'-книга"
    assert cells[8] == "'=cmd|'/C calc'!A0"
    assert cells[9] == "'+1+1"
    assert cells[10].startswith("'=HYPERLINK")
    assert cells[11] == "'@SUM(1)"


def test_xlsx_writes_formula_like_text_as_text() -> None:
    body = to_xlsx([_row("=1+1\x07")])

    sheet = load_workbook(io.BytesIO(body)).active
    rows = list(sheet.iter_rows(min_row=2, values_only=False))
    cells = rows[0]

    assert cells[8].value == "=cmd|'/C calc'!A0"
    assert cells[8].data_type == "s"
    # Управляющий знак формат не допускает: он убран, а не уронил выгрузку.
    assert cells[10].value == "=1+1"
    assert cells[10].data_type == "s"
    assert cells[7].value == 31
