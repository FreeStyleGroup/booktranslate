"""Форматы выгрузки перевода.

Их три рода. **Формат оригинала** — там, где документ переписывается по
месту: DOCX, HTML и EPUB. Только так остаётся всё, чего разбор не видел, —
стили, картинки, опись книги, оглавление. **Новый DOCX** — для всех
остальных исходников: PDF обратно не соберётся, а заказчику нужен файл,
который правится, а не только читается. **Текстовые** (простой текст и
Markdown) доступны для любого исходника.

Реестр явный, как и у разборщиков: формат, которого здесь нет, честно
отвечает «не поддерживается» вместо того, чтобы выдать пустой файл.
"""

import enum

from app.models.document import SourceFormat
from app.services.export.base import ExportError, Rendered, Renderer, TranslatedBlock
from app.services.export.docx_builder import DocxBuilder
from app.services.export.docx_writer import DocxRenderer
from app.services.export.markup_writer import EpubRenderer, HtmlRenderer
from app.services.export.text import MarkdownRenderer, TextRenderer


class ExportFormat(str, enum.Enum):
    """Во что собрать перевод."""

    SOURCE = "source"  # формат оригинала, если он поддержан
    DOCX = "docx"  # документ Word: по месту из DOCX, с нуля из остального
    MARKDOWN = "markdown"
    TEXT = "text"


# Форматы исходника, которые собираются обратно в себя.
_IN_PLACE: dict[SourceFormat, Renderer] = {
    SourceFormat.DOCX: DocxRenderer(),
    SourceFormat.HTML: HtmlRenderer(),
    SourceFormat.EPUB: EpubRenderer(),
}

_RENDERERS: dict[ExportFormat, Renderer] = {
    ExportFormat.MARKDOWN: MarkdownRenderer(),
    ExportFormat.TEXT: TextRenderer(),
}


def renderer_for(export_format: ExportFormat, source_format: SourceFormat) -> Renderer:
    """Сборщик под запрошенный формат.

    `source` означает «верни в том же виде, в каком приносили». Если для
    исходного формата сборки по месту нет, ответ — отказ, а не тихая подмена
    на текст: человек, попросивший оригинал, должен узнать, что получит
    другое.

    `docx` из документа Word — та же сборка по месту; из всего остального —
    новый документ с нуля, и в кабинете он так и подписан.
    """
    if export_format is ExportFormat.SOURCE:
        renderer = _IN_PLACE.get(source_format)

        if renderer is None:
            raise ExportError(
                f"Сборка обратно в {source_format.value} пока не поддерживается. "
                "Доступны docx, markdown и text."
            )

        return renderer

    if export_format is ExportFormat.DOCX:
        return _IN_PLACE[SourceFormat.DOCX] if source_format is SourceFormat.DOCX else DocxBuilder()

    return _RENDERERS[export_format]


def formats_for(source_format: SourceFormat) -> list[ExportFormat]:
    """Во что собирается перевод документа этого формата.

    Формат оригинала — первым: ради него сюда и приходят. Новый `docx` — у
    всех, кроме документа Word: для него это то же, что `source`, и два
    одинаковых пункта только путали бы. Список отдаётся клиенту вместе с
    документом — кнопки в кабинете рисуются по нему, а не по второму
    списку на той стороне, который разошёлся бы с этим при первом новом
    формате.
    """
    in_place = [ExportFormat.SOURCE] if source_format in _IN_PLACE else []
    fresh = [] if source_format is SourceFormat.DOCX else [ExportFormat.DOCX]

    return [*in_place, *fresh, ExportFormat.MARKDOWN, ExportFormat.TEXT]


__all__ = [
    "ExportError",
    "ExportFormat",
    "Rendered",
    "Renderer",
    "TranslatedBlock",
    "formats_for",
    "renderer_for",
]
