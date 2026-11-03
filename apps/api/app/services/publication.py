"""Читательская версия: файл из утверждённого выпуска, без служебного.

Текст берётся только по редакциям, которые названы в манифесте, и никогда по текущим: правка
рабочего текста файл выпуска не меняет. Сумма каждой редакции сверяется с манифестом: если база и
манифест разошлись, файла не будет. Служебное остаётся в базе, а готовый файл перед выдачей
проверяется на коды, заменители и заметки проверяющих. Комментарии из исходного Word в такой файл
не идут."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select

from app.models.block import Block
from app.models.chapter import Chapter
from app.models.issue import Issue, IssueEvent
from app.models.release import BookRelease, ChapterRelease, ReleaseStatus
from app.models.review import ReviewCoverage, ReviewRun
from app.models.translation import TranslationRevision
from app.services.chapter_releases import sha256_text
from app.services.errors import ConflictError, NotFoundError, UnsupportedFormatError
from app.services.export import ExportError, ExportFormat, Rendered, TranslatedBlock, renderer_for
from app.services.export.docx_writer import without_comments
from app.services.export.scan import NOTE_MIN_LENGTH, readable_text, scan
from app.services.exporting import EXPORT_ROLES, Export, ExportService


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
                "Формат оригинала — только у книги целиком. Для главы доступны docx, markdown "
                "и text."
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
