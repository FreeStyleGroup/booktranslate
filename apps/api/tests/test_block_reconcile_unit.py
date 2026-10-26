"""Сопоставление глав и блоков с новым разбором — без базы."""

import uuid

import pytest

from app.models.block import BlockKind
from app.models.book_object import ObjectType
from app.services.block_reconcile import (
    AnchorNotFoundError,
    Create,
    Existing,
    Fresh,
    Keep,
    PlacedEntry,
    Retire,
    block_hash,
    heading_title,
    locate,
    master_checksum,
    match,
    object_hash,
    reconcile,
)
from app.services.parsers import ParsedBlock


def para(text: str, **location: object) -> ParsedBlock:
    return ParsedBlock(text=text, kind=BlockKind.PARAGRAPH, location=dict(location))


def heading(text: str, **location: object) -> ParsedBlock:
    return ParsedBlock(text=text, kind=BlockKind.HEADING, location={"level": 2, **location})


def existing(blocks: list[ParsedBlock]) -> list[Existing]:
    return [
        Existing(id=uuid.uuid4(), source_hash=block_hash(b.kind, b.text), source_text=b.text)
        for b in blocks
    ]


def section(title: str | None, **locator: object) -> dict[str, object]:
    return {"title": title, "locator": dict(locator)}


# ---------- reconcile ----------


def test_unchanged_text_keeps_every_block() -> None:
    """Критерий процесса: повторный разбор не меняет коды неизменившихся блоков."""
    blocks = [heading("1 Intro"), para("One."), para("Two.")]

    steps = reconcile(existing(blocks), blocks)

    assert steps == [Keep(0, 0), Keep(1, 1), Keep(2, 2)]


def test_edited_paragraph_gets_new_block_with_lineage() -> None:
    old = [heading("1 Intro"), para("One."), para("Two.")]
    known = existing(old)
    new = [heading("1 Intro"), para("One, corrected."), para("Two.")]

    steps = reconcile(known, new)

    assert Keep(0, 0) in steps and Keep(2, 2) in steps
    assert Retire(1) in steps
    # Прежний код не переиспользуется: новый блок, но родство видно.
    assert Create(parsed=1, parent=known[1].id) in steps


def test_split_paragraph_children_point_to_parent() -> None:
    old = [para("First half. Second half.")]
    known = existing(old)
    new = [para("First half."), para("Second half.")]

    steps = reconcile(known, new)

    assert Retire(0) in steps
    assert Create(parsed=0, parent=known[0].id) in steps
    assert Create(parsed=1, parent=known[0].id) in steps


def test_ambiguous_rewrite_invents_no_lineage() -> None:
    """Несколько прежних на месте нескольких новых — родство не выдумывается."""
    old = [para("A."), para("B.")]
    new = [para("C."), para("D."), para("E.")]

    steps = reconcile(existing(old), new)

    assert all(step.parent is None for step in steps if isinstance(step, Create))


def test_inserted_paragraph_shifts_nothing_else() -> None:
    old = [para("One."), para("Two.")]
    new = [para("One."), para("Inserted."), para("Two.")]

    steps = reconcile(existing(old), new)

    assert steps == [Keep(0, 0), Create(parsed=1, parent=None), Keep(1, 2)]


def test_kind_change_is_a_different_block() -> None:
    """Строка, ставшая заголовком, — другой блок: старый вид с прежним кодом был бы неправдой."""
    old = [para("Results")]
    new = [heading("Results")]

    steps = reconcile(existing(old), new)

    assert Retire(0) in steps


# ---------- locate ----------


BOOK = [
    heading("Intro"),  # 0
    para("Text."),  # 1
    heading("Chapter 1"),  # 2
    para("A."),  # 3
    heading("Chapter 2"),  # 4
    para("B."),  # 5
]


def test_chapter_is_found_by_its_heading() -> None:
    start, end = locate(
        BOOK,
        first_section=section("Chapter 1"),
        previous_start=2,
        following_section=section("Chapter 2"),
        following_start=4,
    )

    assert (start, end) == (2, 4)


def test_chapter_moves_with_its_heading_when_parsing_changed() -> None:
    """Исправленный разборщик добавил блок раньше главы — глава нашлась на новом месте."""
    shifted = [para("Cover."), *BOOK]

    start, end = locate(
        shifted,
        first_section=section("Chapter 1"),
        previous_start=2,
        following_section=section("Chapter 2"),
        following_start=4,
    )

    assert (start, end) == (3, 5)


def test_same_heading_twice_picks_the_nearest() -> None:
    """Два «Введения» в книге — берётся то, что ближе к прежнему месту главы."""
    book = [heading("Introduction"), para("A."), heading("Part 2"), heading("Introduction")]

    start, _ = locate(
        book,
        first_section=section("Introduction"),
        previous_start=3,
        following_section=None,
        following_start=None,
    )

    assert start == 3


def test_last_chapter_ends_with_the_book() -> None:
    _, end = locate(
        BOOK,
        first_section=section("Chapter 2"),
        previous_start=4,
        following_section=None,
        following_start=None,
    )

    assert end == len(BOOK)


def test_epub_chapter_without_heading_is_found_by_file() -> None:
    book = [
        para("A.", href="one.xhtml"),
        para("B.", href="two.xhtml"),
        para("C.", href="two.xhtml"),
    ]

    start, end = locate(
        book,
        first_section=section(None, href="two.xhtml"),
        previous_start=1,
        following_section=None,
        following_start=None,
    )

    assert (start, end) == (1, 3)


def test_missing_heading_is_reported_not_guessed() -> None:
    with pytest.raises(AnchorNotFoundError, match="Chapter 9"):
        locate(
            BOOK,
            first_section=section("Chapter 9"),
            previous_start=2,
            following_section=None,
            following_start=None,
        )


# ---------- суммы и названия ----------


def test_checksum_depends_on_order_and_text() -> None:
    one = master_checksum([(BlockKind.PARAGRAPH, "A."), (BlockKind.PARAGRAPH, "B.")], [])

    assert one == master_checksum([(BlockKind.PARAGRAPH, "A."), (BlockKind.PARAGRAPH, "B.")], [])
    assert one != master_checksum([(BlockKind.PARAGRAPH, "B."), (BlockKind.PARAGRAPH, "A.")], [])
    # Пробел — тоже текст мастера: суммы обязаны различаться.
    assert one != master_checksum([(BlockKind.PARAGRAPH, "A. "), (BlockKind.PARAGRAPH, "B.")], [])


def test_checksum_covers_objects_and_their_places() -> None:
    """Рисунок — часть версии: другое изображение или другое место — другая сумма."""
    blocks = [(BlockKind.PARAGRAPH, "A."), (BlockKind.PARAGRAPH, "B.")]

    def figure(checksum: str, at: int) -> PlacedEntry:
        return PlacedEntry(
            type=ObjectType.FIGURE, checksum=checksum, at=at, content=(), caption=None
        )

    with_figure = master_checksum(blocks, [figure("a" * 64, 1)])

    assert with_figure == master_checksum(blocks, [figure("a" * 64, 1)])
    assert with_figure != master_checksum(blocks, [])
    assert with_figure != master_checksum(blocks, [figure("b" * 64, 1)])
    assert with_figure != master_checksum(blocks, [figure("a" * 64, 2)])


def test_objects_match_by_content_and_never_split() -> None:
    """Объект без текста сопоставляется по сумме; разделения у объектов не бывает."""
    old = [
        Existing(id=uuid.uuid4(), source_hash=object_hash(ObjectType.TABLE, "t1"), source_text=None)
    ]
    fresh = [
        Fresh(source_hash=object_hash(ObjectType.TABLE, "t1"), source_text=None),
        Fresh(source_hash=object_hash(ObjectType.FIGURE, "f1"), source_text=None),
    ]

    steps = match(old, fresh)

    assert Keep(existing=0, parsed=0) in steps
    assert Create(parsed=1, parent=None) in steps

    changed = match(old, [Fresh(source_hash=object_hash(ObjectType.TABLE, "t2"), source_text=None)])
    assert changed == [Retire(existing=0), Create(parsed=0, parent=old[0].id)]


def test_heading_title_is_one_bounded_line() -> None:
    assert heading_title("Chapter 1.\n  Pumps") == "Chapter 1. Pumps"
    assert len(heading_title("x " * 1000)) == 500


def test_adjacent_edits_keep_their_own_lineage() -> None:
    """Правка одного абзаца и разделение соседнего — у каждого свой предок.

    Алгоритм сравнения сливает соседние изменения в один участок; родство
    внутри участка обязано остаться точным, а не пропасть целиком.
    """
    old = [para("Head."), para("First."), para("Second. Third."), para("Tail.")]
    known = existing(old)
    new = [para("Head."), para("First, fixed."), para("Second."), para("Third."), para("Tail.")]

    created = {
        step.parsed: step.parent for step in reconcile(known, new) if isinstance(step, Create)
    }

    assert created == {1: known[1].id, 2: known[2].id, 3: known[2].id}
