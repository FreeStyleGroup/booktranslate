"""Читательская версия: файл из утверждённого выпуска, без служебного.

Текст берётся только по редакциям, которые названы в манифесте, и никогда по текущим: правка
рабочего текста файл выпуска не меняет. Сумма каждой редакции сверяется с манифестом: если база и
манифест разошлись, файла не будет. Служебное остаётся в базе, а готовый файл перед выдачей
проверяется на коды, заменители и заметки проверяющих. Комментарии из исходного Word в такой файл
не идут."""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select

from app.models.block import Block, BlockKind
from app.models.book import BookEdition
from app.models.book_object import ObjectType
from app.models.chapter import Chapter
from app.models.issue import Issue, IssueEvent
from app.models.project import Project
from app.models.release import BookRelease, ChapterRelease, ReleaseStatus
from app.models.review import ReviewCoverage, ReviewRun
from app.models.translation import TranslationRevision
from app.services.assembly import TOC_LEVELS
from app.services.book_objects import ObjectService, PlacedObject
from app.services.chapter_releases import sha256_text
from app.services.errors import ConflictError, NotFoundError, UnsupportedFormatError
from app.services.export import ExportError, ExportFormat, Rendered, TranslatedBlock, renderer_for
from app.services.export.docx_writer import without_comments
from app.services.export.pdf import (
    FigureElement,
    FormulaElement,
    PdfDocument,
    TableCell,
    TableElement,
    TextElement,
    TocEntry,
    asset_url,
    text_layer,
)
from app.services.export.scan import NOTE_MIN_LENGTH, readable_text, scan
from app.services.exporting import EXPORT_ROLES, Export, ExportService
from app.services.object_extraction import picture_key


@dataclass(frozen=True, slots=True)
class PublicationView:
    """Содержание выпуска: блоки в порядке книги и то, с чем сверять готовый файл."""

    blocks: list[TranslatedBlock]
    source_texts: list[str]
    notes: list[str]


class PublicationService(ExportService):
    async def chapter_release(
        self, release_id: uuid.UUID, *, export_format: ExportFormat
    ) -> Export:
        self._context.require(*EXPORT_ROLES)

        if export_format is ExportFormat.SOURCE:
            raise UnsupportedFormatError(
                "Формат оригинала — только у книги целиком. Для главы доступны Word, Markdown "
                "и простой текст."
            )

        release = await self._session.scalar(
            self.scoped(ChapterRelease).where(ChapterRelease.id == release_id)
        )
        if release is None:
            raise NotFoundError("Такой версии главы нет")
        if release.status is not ReleaseStatus.APPROVED:
            raise ConflictError(f"{release.code} не утверждена: читательской версии у неё нет")

        return await self._publish([release], stem=release.code, export_format=export_format)

    async def book_release(self, release_id: uuid.UUID, *, export_format: ExportFormat) -> Export:
        self._context.require(*EXPORT_ROLES)

        release = await self._session.scalar(
            self.scoped(BookRelease).where(BookRelease.id == release_id)
        )
        if release is None:
            raise NotFoundError("Такого выпуска нет")

        return await self.render_book_release(release, export_format=export_format)

    async def render_book_release(
        self, release: BookRelease, *, export_format: ExportFormat
    ) -> Export:
        ids = [uuid.UUID(row["release_id"]) for row in release.manifest["chapters"]]
        rows = {
            row.id: row
            for row in await self._session.scalars(
                self.scoped(ChapterRelease).where(ChapterRelease.id.in_(ids))
            )
        }
        ordered = [rows[item] for item in ids]

        return await self._publish(ordered, stem=release.code, export_format=export_format)

    async def _publish(
        self, releases: Sequence[ChapterRelease], *, stem: str, export_format: ExportFormat
    ) -> Export:
        chapter = await self._session.get_one(Chapter, releases[0].chapter_id)
        document = await self._document(chapter.source_document_id)

        try:
            renderer = renderer_for(export_format, document.source_format)
        except ExportError as error:
            raise UnsupportedFormatError(str(error)) from error

        view = await self.view(releases)
        rendered = await self._render(renderer, view.blocks, document)

        try:
            if rendered.suffix == ".docx":
                rendered = Rendered(
                    content=without_comments(rendered.content),
                    media_type=rendered.media_type,
                    suffix=rendered.suffix,
                )

            found = scan(readable_text(rendered), source_texts=view.source_texts, notes=view.notes)
        except ExportError as error:
            raise ConflictError(str(error)) from error

        if found:
            raise ConflictError(
                "В читательской версии нашлось служебное: "
                + "; ".join(found[:10])
                + ". Файл не выдан."
            )

        return Export(stem=stem, rendered=rendered, untranslated=0, ending="")

    async def view(self, releases: Sequence[ChapterRelease]) -> PublicationView:
        """Содержание по манифестам. Других источников текста здесь нет."""
        entries = [row for release in releases for row in release.manifest["blocks"]]
        revision_ids = [uuid.UUID(row["revision_id"]) for row in entries]

        rows = await self._session.execute(
            select(TranslationRevision, Block)
            .join(Block, Block.id == TranslationRevision.block_id)
            .where(
                TranslationRevision.organization_id == self.organization_id,
                TranslationRevision.id.in_(revision_ids),
            )
        )
        found = {revision.id: (revision, block) for revision, block in rows.all()}
        blocks: list[TranslatedBlock] = []
        source_texts: list[str] = []

        for entry in entries:
            pair = found.get(uuid.UUID(entry["revision_id"]))
            if pair is None or str(pair[1].id) != entry["id"]:
                raise ConflictError("Манифест расходится с базой: редакция не найдена")

            revision, block = pair
            if sha256_text(revision.text) != entry["text_sha256"]:
                raise ConflictError("Манифест расходится с базой: текст редакции изменён")

            blocks.append(
                TranslatedBlock(text=revision.text, kind=block.kind, location=block.source_location)
            )
            source_texts.append(block.source_text)

        return PublicationView(
            blocks=blocks,
            source_texts=source_texts,
            notes=await self._notes([release.chapter_id for release in releases]),
        )

    async def pdf_document(self, release: BookRelease) -> tuple[PdfDocument, PublicationView]:
        """Содержание PDF: те же редакции из того же манифеста, что и у DOCX."""
        ids = [uuid.UUID(row["release_id"]) for row in release.manifest["chapters"]]
        rows = {
            row.id: row
            for row in await self._session.scalars(
                self.scoped(ChapterRelease).where(ChapterRelease.id.in_(ids))
            )
        }
        ordered = [rows[item] for item in ids]
        view = await self.view(ordered)

        book = await self._session.get_one(BookEdition, release.book_id)
        project = await self._session.get_one(Project, book.project_id)
        document = PdfDocument(title=book.title, language=project.target_language)
        loaded: dict[str, str] = {}

        for chapter_release in ordered:
            await self._fill(document, chapter_release, loaded)

        return document, view

    async def check_pdf(self, content: bytes, view: PublicationView) -> None:
        text = await asyncio.to_thread(text_layer, content)
        found = scan(text, source_texts=view.source_texts, notes=view.notes)

        if found:
            raise ConflictError(
                "В PDF нашлось служебное: " + "; ".join(found[:10]) + ". Файл не сохранён."
            )

    async def _fill(
        self, document: PdfDocument, release: ChapterRelease, loaded: dict[str, str]
    ) -> None:
        kept = {
            uuid.UUID(row["id"]): uuid.UUID(row["revision_id"])
            for row in release.manifest["blocks"]
        }
        wanted_objects = {uuid.UUID(row["id"]) for row in release.manifest["objects"]}

        blocks = list(
            await self._session.scalars(
                self.scoped(Block).where(Block.id.in_(kept)).order_by(Block.ordinal)
            )
        )
        texts = {
            row.id: row.text
            for row in await self._session.scalars(
                self.scoped(TranslationRevision).where(TranslationRevision.id.in_(kept.values()))
            )
        }
        listing = await ObjectService(self._session, self._context, self._storage).listing(
            release.master_id
        )
        placed = [item for item in listing.objects if item.object.id in wanted_objects]

        tables = {
            item.content[0].id: item
            for item in placed
            if item.object.type is ObjectType.TABLE and item.content
        }
        cells = {cell.id for item in tables.values() for cell in item.content}
        before: dict[uuid.UUID, list[PlacedObject]] = {}
        tail: list[PlacedObject] = []

        for item in placed:
            if item.object.type is ObjectType.FIGURE or (
                item.object.type is ObjectType.EQUATION and not item.content
            ):
                if item.before is not None and item.before.id in kept:
                    before.setdefault(item.before.id, []).append(item)
                else:
                    tail.append(item)

        for block in blocks:
            for item in before.get(block.id, []):
                await self._place_object(document, item, loaded)

            table = tables.get(block.id)
            if table is not None:
                document.elements.append(_table(table, kept, texts))
                continue
            if block.id in cells:
                continue

            level = block.source_location.get("level")
            level = level if isinstance(level, int) else 1
            text = texts[kept[block.id]]
            document.elements.append(
                TextElement(block_id=str(block.id), kind=block.kind, text=text, level=level)
            )
            if block.kind is BlockKind.HEADING and level <= TOC_LEVELS:
                document.toc.append(TocEntry(level=level, text=text, block_id=str(block.id)))

        for item in tail:
            await self._place_object(document, item, loaded)

    async def _place_object(
        self, document: PdfDocument, item: PlacedObject, loaded: dict[str, str]
    ) -> None:
        if item.object.type is ObjectType.EQUATION:
            text = str(item.object.payload.get("text") or "").strip()
            if text:
                document.elements.append(FormulaElement(text))
            return

        urls: list[str] = []
        alts: list[str] = []

        for entry in item.object.payload.get("images", []):
            digest = entry.get("sha256")
            if not digest:
                continue

            url = loaded.get(digest)
            if url is None:
                url = asset_url(len(loaded))
                parts = [
                    chunk
                    async for chunk in self._storage.stream(
                        picture_key(self.organization_id, digest)
                    )
                ]
                document.images[url] = (
                    b"".join(parts),
                    entry.get("media_type") or "application/octet-stream",
                )
                loaded[digest] = url

            urls.append(url)
            alts.append(str(entry.get("alt") or ""))

        if urls:
            document.elements.append(FigureElement(urls=urls, alts=alts))

    async def _notes(self, chapter_ids: Sequence[uuid.UUID]) -> list[str]:
        """Что писали проверяющие: этого не должно быть в файле читателя."""
        coverage = await self._session.scalars(
            select(ReviewCoverage.note)
            .join(ReviewRun, ReviewRun.id == ReviewCoverage.run_id)
            .where(
                ReviewCoverage.organization_id == self.organization_id,
                ReviewRun.chapter_id.in_(chapter_ids),
                func.length(ReviewCoverage.note) >= NOTE_MIN_LENGTH,
            )
        )
        events = await self._session.scalars(
            select(IssueEvent.note)
            .join(Issue, Issue.id == IssueEvent.issue_id)
            .where(
                IssueEvent.organization_id == self.organization_id,
                Issue.chapter_id.in_(chapter_ids),
                func.length(IssueEvent.note) >= NOTE_MIN_LENGTH,
            )
        )
        descriptions = await self._session.scalars(
            select(Issue.description).where(
                Issue.organization_id == self.organization_id,
                Issue.chapter_id.in_(chapter_ids),
                func.length(Issue.description) >= NOTE_MIN_LENGTH,
            )
        )

        return [row for row in (*coverage, *events, *descriptions) if row is not None]


def _table(
    item: PlacedObject, kept: dict[uuid.UUID, uuid.UUID], texts: dict[uuid.UUID, str]
) -> TableElement:
    """Таблица по её сетке: объединённые ячейки как в книге, текст из манифеста."""
    by_place = {
        (block.source_location.get("row"), block.source_location.get("column")): block
        for block in item.content
    }
    grid = item.object.payload
    rows: list[list[TableCell]] = [[] for _ in range(int(grid.get("rows") or 0))]

    for meta in grid.get("cells", []):
        block = by_place.get((meta.get("row"), meta.get("col")))
        row_no = int(meta.get("row") or 0)
        if not 0 <= row_no < len(rows):
            continue

        revision = kept.get(block.id) if block is not None else None
        rows[row_no].append(
            TableCell(
                text=texts.get(revision, "") if revision is not None else "",
                rowspan=int(meta.get("rowspan") or 1),
                colspan=int(meta.get("colspan") or 1),
                header=bool(meta.get("header")),
                block_id=str(block.id) if block is not None else None,
            )
        )

    return TableElement(rows=rows)
