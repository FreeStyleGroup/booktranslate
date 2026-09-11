"""Сборка HTML и EPUB: тот же обход, что у разбора, и только текст под замену.

Без базы: разметка разбирается тем же кодом, что и в бою, переводы
раскладываются по номерам блоков и вписываются обратно. Два обещания:
номер блока значит одно и то же на обеих сторонах — служебный тег внутри
абзаца не сдвигает всю главу; картинки, переносы и сноски внутри абзаца
переживают перевод.
"""

from bs4 import BeautifulSoup, Tag

from app.services.export.markup_writer import rewrite_html
from app.services.parsers.markup import block_text, blocks_from_html, find_blocks


def translated(markup: str, translate: dict[str, str]) -> str:
    """Разобрать, перевести по словарю «исходник → перевод», собрать.

    Блок, которого в словаре нет, роняет тест с KeyError: значит, разбор
    прочитал не то, что ожидалось, и это надо увидеть, а не спрятать.
    """
    translations = {
        block.location["block"]: translate[block.text] for block in blocks_from_html(markup)
    }

    return rewrite_html(markup, translations)


def only_paragraph(markup: str, name: str = "p") -> Tag:
    element = BeautifulSoup(markup, "html.parser").find(name)
    assert isinstance(element, Tag)

    return element


def test_inline_markup_survives_translation() -> None:
    """Картинка, перенос и сноска внутри абзаца — не текст, и терять их нельзя."""
    source = '<p>Look <img src="a.png"/> at<br/>this<sup><a href="#n1">1</a></sup> now</p>'

    result = translated(source, {"Look at this 1 now": "Смотрите сюда"})
    paragraph = only_paragraph(result)

    assert paragraph.get_text(" ", strip=True) == "Смотрите сюда"
    assert paragraph.find("img") is not None
    assert paragraph.find("br") is not None
    # Ссылка на сноску осталась ссылкой, пусть и без номера: адрес — не текст.
    anchor = paragraph.find("a")
    assert isinstance(anchor, Tag)
    assert anchor["href"] == "#n1"
    assert anchor.parent is not None and anchor.parent.name == "sup"


def test_translation_goes_into_the_first_text_node() -> None:
    """Перевод занимает место первого текста, а не дописывается в конец."""
    source = "<p><b>Warning!</b> Disconnect the power.</p>"

    result = translated(source, {"Warning! Disconnect the power.": "Внимание! Отключите питание."})

    assert result == "<p><b>Внимание! Отключите питание.</b></p>"


def test_script_inside_block_is_neither_counted_nor_lost() -> None:
    """Скрипт разбор не читал: блок из одного скрипта не занимает номер."""
    source = "<p><script>track()</script></p><p>Second</p>"

    result = translated(source, {"Second": "Второй"})

    assert "track()" in result
    assert "<p>Второй</p>" in result
    assert "Second" not in result


def test_script_next_to_text_stays_in_place() -> None:
    source = "<p>Text<script>track()</script></p>"

    result = translated(source, {"Text": "Текст"})

    assert result == "<p>Текст<script>track()</script></p>"


def test_noscript_only_block_does_not_shift_numbering() -> None:
    """У разбора такой блок пуст — у сборки он должен быть пуст точно так же."""
    source = "<p><noscript>Enable JS</noscript></p><p>Second</p>"

    result = translated(source, {"Second": "Второй"})

    assert "Enable JS" in result
    assert "<p>Второй</p>" in result
    assert "Second" not in result


def test_block_nested_inside_noscript_does_not_shift_numbering() -> None:
    """Абзац внутри noscript разбор не видел — вложенным он не считается."""
    source = "<p>Intro<noscript><p>No JS</p></noscript></p><p>Second</p>"

    result = translated(source, {"Intro": "Вступление", "Second": "Второй"})

    assert "Вступление" in result
    assert "<p>Второй</p>" in result
    assert "Second" not in result
    assert "<noscript><p>No JS</p></noscript>" in result


def test_parser_and_writer_walk_the_same_blocks() -> None:
    """Один обход на обе стороны: что разбор отдал, то сборка и находит."""
    source = (
        "<html><head><title>Title</title><style>p{}</style></head><body>"
        "<h2>Section</h2>"
        "<p><noscript>Enable JS</noscript></p>"
        "<p>Intro<noscript><p>No JS</p></noscript></p>"
        "<ul><li>First</li><li><script>x</script></li></ul>"
        "<td>Cell<title>ignored</title></td>"
        "</body></html>"
    )

    parsed = [block.text for block in blocks_from_html(source)]
    walked = [block_text(element) for element in find_blocks(BeautifulSoup(source, "html.parser"))]

    assert parsed == walked == ["Section", "Intro", "First", "Cell"]
