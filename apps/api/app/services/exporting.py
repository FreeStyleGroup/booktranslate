"""Выгрузка переведённого документа.

Собирает из сегментов то, что можно отдать заказчику. Три вещи здесь важнее
самой записи файла.

**Сегменты снова становятся блоками.** Длинный абзац при разборе резался на
части ради удобства перевода и проверок; в файл должен уйти абзац, а не
строки, на которые его делили. Части узнаются по номеру в разметке
положения — он проставлен только там, где резали.

**Непереведённое не выдаётся за перевод.** По умолчанию выгрузка
недоделанного документа отклоняется с числом незакрытых сегментов. Отдать
книгу, где каждый десятый абзац остался на английском, молча — худшее, что
здесь можно сделать: получатель заметит это позже всех.

**Черновик доступен явным разрешением.** Он нужен: показать заказчику
середину работы, отдать главу на вычитку. Тогда непереведённые блоки идут
исходным текстом, а сколько их было — сказано в ответе.
"""

import asyncio
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.organization import Role
from app.models.segment import Segment, SegmentStatus
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, NotFoundError, UnsupportedFormatError
from app.services.export import (
    ExportError,
    ExportFormat,
    Rendered,
    Renderer,
    TranslatedBlock,
    renderer_for,
)
from app.services.storage import ObjectStorage

# Забрать перевод может кто угодно, кроме тех, кому и смотреть нечего.
# Наблюдатель здесь уместен: выгрузка — это чтение.
EXPORT_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER, Role.VIEWER)

# Статусы, при которых сегмент считается переведённым. NEW — нет; всё
# остальное означает, что перевод есть, а чей он и принят ли — вопрос
# приёмки, а не выгрузки.
UNTRANSLATED = SegmentStatus.NEW


@dataclass(slots=True)
class Export:
    document: Document
    rendered: Rendered
    # Сколько блоков ушло в файл исходным текстом. Ноль означает полный
    # перевод; всё прочее клиент обязан показать.
    untranslated: int

    @property
    def filename(self) -> str:
        """Имя файла: исходное плюс язык, чтобы перевод не затёр оригинал."""
        stem = Path(self.document.original_filename or self.document.title).stem

        return f"{stem}-перевод{self.rendered.suffix}"


class ExportService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def export(
        self,
        document_id: uuid.UUID,
        *,
        export_format: ExportFormat = ExportFormat.SOURCE,
        allow_untranslated: bool = False,
    ) -> Export:
        self._context.require(*EXPORT_ROLES)

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        try:
            renderer = renderer_for(export_format, document.source_format)
        except ExportError as error:
            raise UnsupportedFormatError(str(error)) from error

        segments = list(
            await self._session.scalars(
                self.scoped(Segment)
                .where(Segment.document_id == document_id)
                .order_by(Segment.position)
            )
        )
        if not segments:
            raise ConflictError("Документ ещё не разобран на сегменты")

        blocks = _to_blocks(segments)
        untranslated = sum(1 for block in blocks if not block.translated)

        if untranslated and not allow_untranslated:
            raise ConflictError(
                f"Не переведено блоков: {untranslated}. Выгрузить черновик можно "
                "с allow_untranslated=true — непереведённое уйдёт исходным текстом."
            )

        rendered = await self._render(renderer, blocks, document)

        return Export(document=document, rendered=rendered, untranslated=untranslated)

    async def _render(
        self, renderer: Renderer, blocks: list[TranslatedBlock], document: Document
    ) -> Rendered:
        """Собрать файл, при необходимости скачав исходник во временный.

        Сборка блокирующая — и разбор Word, и запись архива. В потоке
        событий она остановила бы обслуживание остальных запросов.
        """
        if not renderer.needs_source:
            try:
                return await asyncio.to_thread(renderer.render, blocks, source=None)
            except ExportError as error:
                raise ConflictError(str(error)) from error

        descriptor, name = tempfile.mkstemp(prefix="booktranslate-export-")
        path = Path(name)

        try:
            with os.fdopen(descriptor, "wb") as handle:
                async for chunk in self._storage.stream(document.storage_key):
                    await asyncio.to_thread(handle.write, chunk)

            return await asyncio.to_thread(renderer.render, blocks, source=path)
        except ExportError as error:
            raise ConflictError(str(error)) from error
        finally:
            path.unlink(missing_ok=True)


def _to_blocks(segments: list[Segment]) -> list[TranslatedBlock]:
    """Собрать сегменты обратно в блоки исходника.

    Части одного блока идут подряд и помечены номером `part`; сегмент без
    него — блок целиком. Склейка по пробелу: резали по границам предложений,
    и разделителем между ними был именно он.
    """
    blocks: list[TranslatedBlock] = []
    parts: list[Segment] = []

    def flush() -> None:
        if parts:
            blocks.append(_merge(parts))
            parts.clear()

    for segment in segments:
        place = segment.source_location or {}
        part = place.get("part")

        if not isinstance(part, int):
            flush()
            blocks.append(_merge([segment]))
            continue

        # Ноль означает начало нового блока: части нумеруются с нуля, и
        # опираться на равенство разметки положения не нужно.
        if part == 0:
            flush()

        parts.append(segment)

    flush()

    return blocks


def _merge(parts: list[Segment]) -> TranslatedBlock:
    first = parts[0]
    translated = all(part.status is not UNTRANSLATED and part.target_text for part in parts)

    if translated:
        text = " ".join((part.target_text or "").strip() for part in parts)
    else:
        # Смешивать перевод с исходником внутри одного абзаца нельзя: получится
        # текст на двух языках в одном предложении. Абзац идёт целиком
        # исходным.
        text = " ".join(part.source_text.strip() for part in parts)

    place = dict(first.source_location or {})
    place.pop("part", None)

    return TranslatedBlock(text=text, kind=first.kind, location=place, translated=translated)
