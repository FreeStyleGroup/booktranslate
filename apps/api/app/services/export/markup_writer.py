"""Сборка HTML и EPUB: перевод вписывается в исходную разметку.

Книга в EPUB — это не текст, а архив: обложка, стили, шрифты, картинки,
опись, оглавление и десятки файлов глав, связанных ссылками. Собрать такое
заново из переведённых абзацев нельзя, и попытка обернулась бы книгой без
единой картинки и с рассыпавшимся оглавлением.

Поэтому берётся оригинал и в нём заменяется текст. Обход разметки — тот же
самый, которым читал разборщик (`parsers.markup.find_blocks`), а не его
копия: по номеру блока в этом обходе и восстанавливается соответствие, и
разойтись два обхода не могут, пока обход один. Всё остальное содержимое
архива переносится байт в байт.

Внутреннее оформление абзаца при замене теряется: перевод занимает место
первого текста в блоке, остальной текст убирается. В сегменте лежит текст,
и разложить перевод по прежним `<b>` и ссылкам не по чему — та же граница,
что и в DOCX. Но сами теги внутри блока — картинка, перенос, ссылка на
сноску — остаются: в тексте сегмента их не было, и терять их при сборке
значит портить книгу. Разметка самого блока (заголовок остаётся `h2`, пункт
списка — `li`, классы и атрибуты на месте) сохраняется.
"""

import io
import zipfile
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.export.base import ExportError, Rendered, TranslatedBlock
from app.services.parsers.markup import block_strings, find_blocks


def rewrite_html(markup: str, translations: dict[int, str]) -> str:
    """Заменить текст блоков разметки переводом.

    Ключ — порядковый номер блока в том же обходе, которым читал разборщик.
    Блока, для которого перевода нет, обход не трогает: пропуск в середине
    книги не должен сдвигать всё, что за ним.
    """
    soup = BeautifulSoup(markup, "html.parser")

    for index, element in enumerate(find_blocks(soup)):
        text = translations.get(index)
        if text is not None:
            _replace_text(element, text)

    return str(soup)


def _replace_text(element: Tag, text: str) -> None:
    """Вписать перевод на место текста блока, не трогая разметку внутри.

    Перевод занимает первый непустой текстовый узел — вместе с его
    оформлением, как первая руна в DOCX; остальные текстовые узлы
    убираются. Узлы — ровно те, из которых разбор складывал текст сегмента:
    скрипт внутри абзаца он не читал, и здесь он остаётся как был.
    """
    strings = [node for node in block_strings(element) if str(node).strip()]

    # Обход отдаёт только блоки с текстом, так что пустым список не бывает;
    # но перевод в любом случае не должен пропасть молча.
    if not strings:
        element.append(text)
        return

    strings[0].replace_with(text)

    for node in strings[1:]:
        node.extract()


class HtmlRenderer:
    media_type = "text/html; charset=utf-8"
    suffix = ".html"

    @property
    def needs_source(self) -> bool:
        return True

    def render(self, blocks: list[TranslatedBlock], *, source: Path | None) -> Rendered:
        if source is None:
            raise ExportError("Для сборки HTML нужен исходный файл")

        markup = source.read_text(encoding="utf-8", errors="replace")
        translations = {
            number: block.text
            for block, number in ((block, _block_number(block)) for block in blocks)
            if number is not None
        }

        return Rendered(
            content=rewrite_html(markup, translations).encode("utf-8"),
            media_type=self.media_type,
            suffix=self.suffix,
        )


class EpubRenderer:
    media_type = "application/epub+zip"
    suffix = ".epub"

    @property
    def needs_source(self) -> bool:
        return True

    def render(self, blocks: list[TranslatedBlock], *, source: Path | None) -> Rendered:
        if source is None:
            raise ExportError("Для сборки EPUB нужен исходный файл")

        by_chapter = _by_chapter(blocks)
        buffer = io.BytesIO()

        try:
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(buffer, "w") as result:
                for info in original.infolist():
                    data = original.read(info.filename)
                    translations = by_chapter.get(info.filename)

                    if translations:
                        markup = data.decode("utf-8", errors="replace")
                        data = rewrite_html(markup, translations).encode("utf-8")

                    # Запись переносится вместе со своим способом сжатия:
                    # `mimetype` в EPUB обязан лежать без сжатия и первым, и
                    # пересжатие сделало бы книгу нечитаемой для части
                    # читалок.
                    result.writestr(_carried(info), data)
        except zipfile.BadZipFile as error:
            raise ExportError("Исходный файл не читается как EPUB: повреждён архив") from error

        return Rendered(content=buffer.getvalue(), media_type=self.media_type, suffix=self.suffix)


def _carried(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """Запись архива с сохранёнными свойствами, но без прежнего размера.

    Размер и контрольная сумма пересчитываются при записи; имя, дата,
    способ сжатия и права переносятся как есть.
    """
    carried = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
    carried.compress_type = info.compress_type
    carried.external_attr = info.external_attr
    carried.internal_attr = info.internal_attr
    carried.create_system = info.create_system

    return carried


def _by_chapter(blocks: list[TranslatedBlock]) -> dict[str, dict[int, str]]:
    """Переводы, разложенные по файлам глав."""
    chapters: dict[str, dict[int, str]] = {}

    for block in blocks:
        href = block.location.get("href")
        number = _block_number(block)

        if not isinstance(href, str) or number is None:
            continue

        chapters.setdefault(href, {})[number] = block.text

    return chapters


def _block_number(block: TranslatedBlock) -> int | None:
    number: Any = block.location.get("block")

    return number if isinstance(number, int) else None
