"""Черновая выгрузка перевода: главы и книги из текущих редакций.

Это рабочая выгрузка — показать середину работы, отдать главу на вычитку. Выпуск
с манифестом и закреплёнными версиями появится отдельно и этой выгрузкой не будет:
здесь в файл идёт то, что считается текстом книги прямо сейчас.

**Непереведённое не выдаётся за перевод.** По умолчанию выгрузка недоделанного
отклоняется с числом блоков без редакции. Отдать книгу, где каждый десятый абзац
остался на английском, молча — худшее, что здесь можно сделать: получатель заметит
это позже всех. С явным разрешением такие блоки идут исходным текстом, а сколько их
было — сказано в ответе.

**Формат оригинала — только у книги.** Глава в исходном файле — это весь файл с
переведённым куском, и выглядеть результат будет как перевод, которым не является.
"""

import asyncio
import os
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book import BookEdition
from app.models.chapter import Chapter
from app.models.document import Document
from app.models.organization import Role
from app.models.translation import TranslationRevision
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


@dataclass(slots=True)
class Export:
    stem: str
    rendered: Rendered
    # Сколько блоков ушло в файл исходным текстом. Ноль означает полный
    # перевод; всё прочее клиент обязан показать.
    untranslated: int
    # Пометка в имени, чтобы перевод не затёр оригинал. У выпуска она не нужна: у него свой код.
    ending: str = "-перевод"

    @property
    def filename(self) -> str:
        return f"{self.stem}{self.ending}{self.rendered.suffix}"


class ExportService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def chapter(
        self,
        chapter_id: uuid.UUID,
        *,
        export_format: ExportFormat,
        allow_untranslated: bool = False,
        codes: bool = False,
    ) -> Export:
        self._context.require(*EXPORT_ROLES)

        if export_format is ExportFormat.SOURCE:
            raise UnsupportedFormatError(
                "Формат оригинала — только у книги целиком. Для главы доступны docx, markdown "
                "и text."
            )

        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        document = await self._document(chapter.source_document_id)

        return await self._build(
            [chapter],
            document,
            stem=chapter.code or f"глава-{chapter.ordinal}",
            export_format=export_format,
            allow_untranslated=allow_untranslated,
            codes=codes,
        )

    async def book(
        self,
        book_id: uuid.UUID,
        *,
        export_format: ExportFormat,
        allow_untranslated: bool = False,
        codes: bool = False,
    ) -> Export:
        self._context.require(*EXPORT_ROLES)

        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))
        if book is None:
            raise NotFoundError("Книга не найдена")

        chapters = list(
            await self._session.scalars(
                self.scoped(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)
            )
        )
        if not chapters:
            raise ConflictError("В книге ещё нет глав")

        # Главы книги нарезаны из одного основного файла: у издания он один.
        document = await self._document(chapters[0].source_document_id)

        return await self._build(
            chapters,
            document,
            stem=Path(document.original_filename or book.title).stem,
            export_format=export_format,
            allow_untranslated=allow_untranslated,
            codes=codes,
        )

    async def _build(
        self,
        chapters: Sequence[Chapter],
        document: Document,
        *,
        stem: str,
        export_format: ExportFormat,
        allow_untranslated: bool,
        codes: bool = False,
    ) -> Export:
        try:
            renderer = renderer_for(export_format, document.source_format)
        except ExportError as error:
            raise UnsupportedFormatError(str(error)) from error

        blocks = await self._blocks(chapters, codes=codes)
        if not blocks:
            raise ConflictError("В главе нет блоков: сначала извлеките мастер")

        untranslated = sum(1 for block in blocks if not block.translated)

        if untranslated and not allow_untranslated:
            raise ConflictError(
                f"Не переведено блоков: {untranslated}. Выгрузить черновик можно с "
                "allow_untranslated=true — непереведённое уйдёт исходным текстом."
            )

        rendered = await self._render(renderer, blocks, document)

        return Export(
            stem=stem,
            rendered=rendered,
            untranslated=untranslated,
            ending="-рабочая" if codes else "-перевод",
        )

    async def _blocks(
        self, chapters: Sequence[Chapter], *, codes: bool = False
    ) -> list[TranslatedBlock]:
        order = {chapter.id: chapter.ordinal for chapter in chapters}
        names = {chapter.id: chapter.code for chapter in chapters}
        rows = await self._session.execute(
            select(Block, TranslationRevision.text)
            .outerjoin(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(
                Block.organization_id == self.organization_id,
                Block.chapter_id.in_(order),
                Block.active.is_(True),
            )
            .order_by(Block.chapter_id, Block.ordinal)
        )
        pairs = sorted(rows.all(), key=lambda row: (order[row[0].chapter_id], row[0].ordinal))

        return [
            TranslatedBlock(
                # Коды только в рабочей выгрузке: читательская собирается из выпуска и без них.
                text=(f"[{names[block.chapter_id]}-{block.code}] " if codes else "")
                + (text if text is not None else block.source_text),
                kind=block.kind,
                location=block.source_location,
                translated=text is not None,
            )
            for block, text in pairs
        ]

    async def _document(self, document_id: uuid.UUID) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Исходный файл не найден")

        return document

    async def _render(
        self, renderer: Renderer, blocks: list[TranslatedBlock], document: Document
    ) -> Rendered:
        """Собрать файл, при необходимости скачав исходник во временный.

        Сборка блокирующая — и разбор Word, и запись архива. В потоке событий она
        остановила бы обслуживание остальных запросов.
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
