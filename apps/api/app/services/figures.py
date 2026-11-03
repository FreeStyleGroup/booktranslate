"""Перевод надписей на рисунках: чтение, перевод, перерисовка, решение.

Перевод идёт тем же путём, что и текст книги: сначала утверждённый глоссарий и проверенная память,
и только потом модель. Что нельзя сделать уверенно, помечается «нужен человек»: неразборчивая
надпись, текст, который не поместился, сбой модели, векторная картинка. Такой рисунок не пройдёт
сам и в автоматическом режиме.

Решение по картинке нужно всегда: перевод утверждён, оставлен оригинал или надписей нет. Без него
глава не выпускается, иначе в книге молча осталась бы непереведённая схема."""

import asyncio
import hashlib
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import BookEdition
from app.models.book_object import BookObject, ObjectType
from app.models.chapter import Chapter
from app.models.figure import DECIDED_STATUSES, FigureStatus, FigureTranslation
from app.models.job import JobKind, JobState, TranslationJob
from app.models.master import ChapterMaster
from app.models.organization import Role
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.book_objects import ObjectService
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.export.base import ExportError
from app.services.export.overlay import OverlayText, image_size, overlay
from app.services.glossary import Glossary, GlossaryService, normalize_term
from app.services.memory import TranslationMemory, fingerprint
from app.services.object_extraction import picture_key
from app.services.providers.base import (
    ProviderError,
    TranslationProvider,
    TranslationRequest,
    Usage,
)
from app.services.providers.figures import SCALE, FigureReader
from app.services.storage import ObjectStorage
from app.services.terminology_gate import TerminologyGate

# Кто запускает и правит; решает проверяющий.
WORKING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)
DECIDING_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER)

# Ниже этой уверенности надпись считается неразборчивой.
CONFIDENCE_MIN = 0.8

# Что можно перерисовать. Вектор и прочее — только решением человека.
RASTER_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

MAX_REGIONS = 200
TEXT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class FigureImage:
    """Картинка главы и её нынешнее состояние."""

    object: BookObject
    code: str
    index: int
    sha256: str
    media_type: str
    current: FigureTranslation | None


@dataclass(frozen=True, slots=True)
class RegionEdit:
    id: str
    x: int
    y: int
    w: int
    h: int
    source_text: str
    target_text: str


def _spend(row: FigureTranslation, usage: Usage) -> None:
    row.input_tokens += usage.input_tokens
    row.output_tokens += usage.output_tokens
    row.cached_input_tokens += usage.cached_input_tokens
    row.cache_write_tokens += usage.cache_write_tokens


class FigureService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def of_chapter(self, chapter_id: uuid.UUID) -> list[FigureImage]:
        """Все картинки текущей версии мастера. Отсутствующие в исходнике не считаются."""
        chapter = await self._chapter(chapter_id)
        master = await self._master(chapter.id)
        if master is None:
            return []

        listing = await ObjectService(self._session, self._context, self._storage).listing(
            master.id, kind=ObjectType.FIGURE
        )
        prefix = f"{chapter.code}-" if chapter.code is not None else ""
        latest = await self._latest(chapter.id)
        found: list[FigureImage] = []

        for item in listing.objects:
            if not item.object.active:
                continue

            for index, entry in enumerate(item.object.payload.get("images", [])):
                digest = entry.get("sha256")
                if not digest:
                    continue

                current = latest.get((item.object.id, index))
                # Перевод другой картинки к этой не относится.
                if current is not None and current.source_sha256 != digest:
                    current = None

                found.append(
                    FigureImage(
                        object=item.object,
                        code=prefix + item.object.code,
                        index=index,
                        sha256=digest,
                        media_type=entry.get("media_type") or "application/octet-stream",
                        current=current,
                    )
                )

        return found

    async def undecided(self, chapter_id: uuid.UUID) -> list[FigureImage]:
        return [
            image
            for image in await self.of_chapter(chapter_id)
            if image.current is None or image.current.status not in DECIDED_STATUSES
        ]

    async def decisions(self, chapter_id: uuid.UUID) -> list[dict[str, Any]]:
        """Решения по картинкам в виде записи манифеста, в порядке главы."""
        return [
            {
                "object_id": str(image.object.id),
                "image_index": image.index,
                "source_sha256": image.sha256,
                "status": image.current.status.value if image.current is not None else None,
                "translation_id": str(image.current.id) if image.current is not None else None,
                "asset_sha256": image.current.asset_sha256 if image.current is not None else None,
            }
            for image in await self.of_chapter(chapter_id)
        ]

    async def request(self, chapter_id: uuid.UUID) -> TranslationJob:
        """Поставить чтение и перевод надписей в очередь."""
        self._context.require(*WORKING_ROLES)

        chapter = await self._chapter(chapter_id)
        waiting = [image for image in await self.of_chapter(chapter.id) if image.current is None]
        if not waiting:
            raise ConflictError("Все рисунки главы уже прочитаны")

        job = TranslationJob(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            kind=JobKind.FIGURES,
            chapter_id=chapter.id,
            state=JobState.WAITING,
            requested_by_id=self._context.user.id,
            items_total=len(waiting),
        )

        try:
            async with self._session.begin_nested():
                self._session.add(job)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("По главе уже идёт работа: дождитесь её конца") from error

        await self._session.commit()

        return job

    async def process(
        self,
        chapter_id: uuid.UUID,
        *,
        reader: FigureReader,
        provider: TranslationProvider,
        tick: Callable[[int], Awaitable[None]] | None = None,
    ) -> int:
        """Прочитать и перевести непрочитанное. Каждая картинка фиксируется сразу."""
        chapter = await self._chapter(chapter_id)
        book = await self._session.get_one(BookEdition, chapter.book_id)
        glossary = await self._glossary(chapter)
        done = 0

        for image in await self.of_chapter(chapter.id):
            if image.current is not None:
                continue

            await self._process_one(chapter, book, image, glossary, reader, provider)
            await self._session.commit()
            done += 1
            if tick is not None:
                await tick(done)

        return done

    async def get(self, translation_id: uuid.UUID) -> FigureTranslation:
        found = await self._session.scalar(
            self.scoped(FigureTranslation).where(FigureTranslation.id == translation_id)
        )
        if found is None:
            raise NotFoundError("Такого перевода рисунка нет")

        return found

    async def asset(self, translation_id: uuid.UUID) -> tuple[bytes, str]:
        found = await self.get(translation_id)
        if found.asset_key is None or found.media_type is None:
            raise NotFoundError("Файла с переводом нет")

        return await self._read(found.asset_key), found.media_type

    async def edit(
        self, translation_id: uuid.UUID, regions: Sequence[RegionEdit], *, note: str | None = None
    ) -> FigureTranslation:
        """Поправить надписи: новая версия и новая перерисовка, прежняя остаётся в истории."""
        self._context.require(*WORKING_ROLES)

        base = await self.get(translation_id)
        if len(regions) > MAX_REGIONS:
            raise InvalidInputError(f"Надписей больше {MAX_REGIONS}")

        latest = await self._latest_of(base.object_id, base.image_index)
        if latest is None or latest.id != base.id:
            raise ConflictError("Перевод уже изменён: откройте его заново")

        before = {row["id"]: row for row in base.regions}
        rows: list[dict[str, Any]] = []

        for item in regions:
            source_text = item.source_text.strip()[:TEXT_LIMIT]
            target_text = item.target_text.strip()[:TEXT_LIMIT]
            if not source_text or not target_text:
                raise InvalidInputError("У каждой надписи должен быть и текст, и перевод")

            old = before.get(item.id)
            same = (
                old is not None
                and old.get("target_text") == target_text
                and (old["x"], old["y"], old["w"], old["h"]) == (item.x, item.y, item.w, item.h)
            )
            rows.append(
                {
                    "id": item.id,
                    "x": item.x,
                    "y": item.y,
                    "w": item.w,
                    "h": item.h,
                    "source_text": source_text,
                    "target_text": target_text,
                    "confidence": old.get("confidence", 1.0) if same and old else 1.0,
                    "origin": old.get("origin", "human") if same and old else "human",
                    "overflow": False,
                }
            )

        chapter = await self._chapter(base.chapter_id)
        content = await self._read(picture_key(self.organization_id, base.source_sha256))
        asset_key, digest, media_type, overflow = await self._draw(chapter, base, content, rows)

        for row in rows:
            row["overflow"] = row["id"] in overflow

        new = FigureTranslation(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=base.book_id,
            chapter_id=base.chapter_id,
            object_id=base.object_id,
            image_index=base.image_index,
            version=base.version + 1,
            source_sha256=base.source_sha256,
            status=FigureStatus.DRAFT,
            regions=rows,
            needs_human=bool(overflow),
            note=(note or "").strip() or None,
            model=base.model,
            asset_key=asset_key,
            asset_sha256=digest,
            media_type=media_type,
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cache_write_tokens=0,
            created_by_id=self._context.user.id,
        )

        try:
            async with self._session.begin_nested():
                self._session.add(new)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Перевод уже изменён: откройте его заново") from error

        await self._session.commit()

        return new

    async def approve(self, translation_id: uuid.UUID) -> FigureTranslation:
        """Человек сверил оригинал с переводом."""
        self._context.require(*DECIDING_ROLES)

        found = await self._locked(translation_id)
        await self._require_latest(found)

        if found.status is not FigureStatus.DRAFT:
            raise ConflictError("По этому рисунку решение уже принято")
        if found.asset_key is None:
            raise ConflictError("Файла с переводом нет: добавьте надписи или оставьте оригинал")

        overflowing = [row["source_text"] for row in found.regions if row.get("overflow")]
        if overflowing:
            raise ConflictError(
                "Текст не поместился на рисунке: "
                + ", ".join(overflowing[:5])
                + ". Сократите перевод или расширьте область"
            )

        return await self._decide(found, FigureStatus.APPROVED, kind="figure.approved")

    async def approve_automatically(self, translation_id: uuid.UUID) -> FigureTranslation:
        """Решение сервиса в автоматическом режиме: только если сервис уверен."""
        found = await self._locked(translation_id)
        await self._require_latest(found)

        if found.status is not FigureStatus.DRAFT or found.asset_key is None or found.needs_human:
            raise ConflictError("Этот рисунок требует решения человека")

        return await self._decide(
            found, FigureStatus.APPROVED, kind="figure.approved_automatically"
        )

    async def keep_original(
        self, object_id: uuid.UUID, index: int, *, note: str | None = None
    ) -> FigureTranslation:
        """Оставить как в книге. Это тоже решение, и оно записывается."""
        self._context.require(*DECIDING_ROLES)

        item = await self._session.scalar(self.scoped(BookObject).where(BookObject.id == object_id))
        if item is None or item.type is not ObjectType.FIGURE:
            raise NotFoundError("Такого рисунка нет")

        images = item.payload.get("images", [])
        if not 0 <= index < len(images) or not images[index].get("sha256"):
            raise NotFoundError("Такого изображения нет")

        chapter = await self._chapter(item.chapter_id)
        latest = await self._latest_of(item.id, index)
        if latest is not None and latest.status in DECIDED_STATUSES:
            current = latest.source_sha256 == images[index]["sha256"]
            if current and latest.status is FigureStatus.KEPT_ORIGINAL:
                raise ConflictError("Оригинал уже оставлен")

        new = FigureTranslation(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            object_id=item.id,
            image_index=index,
            version=(latest.version + 1) if latest is not None else 1,
            source_sha256=images[index]["sha256"],
            status=FigureStatus.KEPT_ORIGINAL,
            regions=[],
            needs_human=False,
            note=(note or "").strip() or None,
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cache_write_tokens=0,
            created_by_id=self._context.user.id,
            decided_by_id=self._context.user.id,
            decided_at=datetime.now(UTC),
        )

        try:
            async with self._session.begin_nested():
                self._session.add(new)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Решение уже принято: обновите страницу") from error

        self._audit("figure.kept_original", new)
        await self._session.commit()

        return new

    # ── внутреннее ──

    async def _process_one(
        self,
        chapter: Chapter,
        book: BookEdition,
        image: FigureImage,
        glossary: Glossary,
        reader: FigureReader,
        provider: TranslationProvider,
    ) -> None:
        latest = await self._latest_of(image.object.id, image.index)
        row = FigureTranslation(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            object_id=image.object.id,
            image_index=image.index,
            version=(latest.version + 1) if latest is not None else 1,
            source_sha256=image.sha256,
            status=FigureStatus.DRAFT,
            regions=[],
            needs_human=True,
            model=reader.name,
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cache_write_tokens=0,
            created_by_id=self._context.user.id,
        )

        if image.media_type not in RASTER_TYPES:
            row.note = "Векторную картинку сервис не перерисовывает: нужно решение человека"
            self._session.add(row)
            return

        content = await self._read(picture_key(self.organization_id, image.sha256))

        try:
            width, height = await asyncio.to_thread(image_size, content)
            reading = await reader.read(content, image.media_type)
        except ProviderError as error:
            row.note = f"Надписи не прочитаны: {error}"
            _spend(row, error.spent)
            self._session.add(row)
            return
        except ExportError as error:
            row.note = str(error)
            self._session.add(row)
            return

        _spend(row, reading.usage)

        if not reading.regions:
            row.status = FigureStatus.NO_TEXT
            row.needs_human = False
            row.decided_at = datetime.now(UTC)
            row.note = "Надписей на рисунке не нашлось"
            self._session.add(row)
            return

        regions: list[dict[str, Any]] = [
            {
                "id": uuid.uuid4().hex[:12],
                "x": region.x * width // SCALE,
                "y": region.y * height // SCALE,
                "w": max(1, region.w * width // SCALE),
                "h": max(1, region.h * height // SCALE),
                "source_text": region.text,
                "target_text": None,
                "confidence": region.confidence,
                "origin": None,
                "overflow": False,
            }
            for region in reading.regions
        ]
        note = await self._translate(regions, book, glossary, provider, row)

        translated = [region for region in regions if region["target_text"]]
        overflow: set[str] = set()

        if translated:
            try:
                key, digest, media_type, overflow = await self._draw(
                    chapter, row, content, translated
                )
            except ExportError as error:
                note = str(error)
            else:
                row.asset_key = key
                row.asset_sha256 = digest
                row.media_type = media_type

        for region in regions:
            region["overflow"] = region["id"] in overflow

        row.regions = regions
        row.note = note
        row.needs_human = (
            note is not None
            or bool(overflow)
            or row.asset_key is None
            or any(float(region["confidence"]) < CONFIDENCE_MIN for region in regions)
            or any(not region["target_text"] for region in regions)
        )
        self._session.add(row)

    async def _translate(
        self,
        regions: list[dict[str, Any]],
        book: BookEdition,
        glossary: Glossary,
        provider: TranslationProvider,
        row: FigureTranslation,
    ) -> str | None:
        """Перевод надписей: то же, что и у текста книги. Возвращает заметку о сбое."""
        terms = {normalize_term(term.source): term for term in glossary.terms}
        pending: list[dict[str, Any]] = []

        for region in regions:
            text = region["source_text"]
            if not any(letter.isalpha() for letter in text):
                region["target_text"], region["origin"] = text, "copy"
            elif normalize_term(text) in terms and terms[normalize_term(text)].settled:
                region["target_text"] = terms[normalize_term(text)].target
                region["origin"] = "glossary"
            else:
                pending.append(region)

        if pending:
            known = await TranslationMemory(self._session, self._context).lookup(
                [region["source_text"] for region in pending],
                source_language=book.source_language,
                target_language=book.target_language,
            )
            still: list[dict[str, Any]] = []
            for region in pending:
                unit = known.get(fingerprint(region["source_text"]))
                if unit is not None:
                    region["target_text"], region["origin"] = unit.target_text, "memory"
                else:
                    still.append(region)
            pending = still

        if not pending:
            return None

        try:
            answer = await provider.translate(
                [
                    TranslationRequest(
                        source_text=region["source_text"],
                        source_language=book.source_language,
                        target_language=book.target_language,
                        key=region["id"],
                        terms=list(glossary.match(region["source_text"])),
                        kind="caption",
                    )
                    for region in pending
                ]
            )
        except ProviderError as error:
            _spend(row, error.spent)

            return f"Надписи не переведены: {error}"

        _spend(row, answer.usage)

        for region in pending:
            text = answer.items.get(region["id"])
            if text:
                region["target_text"], region["origin"] = text.strip()[:TEXT_LIMIT], "model"

        return None

    async def _draw(
        self,
        chapter: Chapter,
        row: FigureTranslation,
        content: bytes,
        regions: Sequence[dict[str, Any]],
    ) -> tuple[str, str, str, set[str]]:
        items = [
            OverlayText(
                id=region["id"],
                x=region["x"],
                y=region["y"],
                w=region["w"],
                h=region["h"],
                text=region["target_text"],
            )
            for region in regions
        ]
        drawn = await asyncio.to_thread(overlay, content, items)
        digest = hashlib.sha256(drawn.content).hexdigest()
        key = f"{self.organization_id}/figures/{chapter.id}/{uuid.uuid4().hex}"
        descriptor, name = tempfile.mkstemp(prefix="booktranslate-figure-")
        path = Path(name)

        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(drawn.content)
            await self._storage.put(key, path)
        finally:
            path.unlink(missing_ok=True)

        return key, digest, drawn.media_type, set(drawn.overflow)

    async def _decide(
        self, found: FigureTranslation, status: FigureStatus, *, kind: str
    ) -> FigureTranslation:
        found.status = status
        found.decided_by_id = self._context.user.id
        found.decided_at = datetime.now(UTC)
        self._audit(kind, found)
        await self._session.commit()
        await self._session.refresh(found)

        return found

    def _audit(self, kind: str, row: FigureTranslation) -> None:
        AuditService(self._session, self._context).record(
            kind=kind,
            subject_type="figure_translation",
            subject_id=row.id,
            payload={
                "object_id": str(row.object_id),
                "image_index": row.image_index,
                "version": row.version,
                "source_sha256": row.source_sha256,
                "asset_sha256": row.asset_sha256,
            },
        )

    async def _require_latest(self, found: FigureTranslation) -> None:
        latest = await self._latest_of(found.object_id, found.image_index)
        if latest is None or latest.id != found.id:
            raise ConflictError("Перевод уже изменён: откройте его заново")

    async def _locked(self, translation_id: uuid.UUID) -> FigureTranslation:
        found = await self._session.scalar(
            self.scoped(FigureTranslation)
            .where(FigureTranslation.id == translation_id)
            .with_for_update()
        )
        if found is None:
            raise NotFoundError("Такого перевода рисунка нет")

        return found

    async def _latest_of(self, object_id: uuid.UUID, index: int) -> FigureTranslation | None:
        found: FigureTranslation | None = await self._session.scalar(
            self.scoped(FigureTranslation)
            .where(
                FigureTranslation.object_id == object_id,
                FigureTranslation.image_index == index,
            )
            .order_by(FigureTranslation.version.desc())
            .limit(1)
        )

        return found

    async def _latest(
        self, chapter_id: uuid.UUID
    ) -> dict[tuple[uuid.UUID, int], FigureTranslation]:
        newest = (
            select(
                FigureTranslation.object_id,
                FigureTranslation.image_index,
                func.max(FigureTranslation.version).label("version"),
            )
            .where(
                FigureTranslation.organization_id == self.organization_id,
                FigureTranslation.chapter_id == chapter_id,
            )
            .group_by(FigureTranslation.object_id, FigureTranslation.image_index)
            .subquery()
        )
        rows = await self._session.scalars(
            self.scoped(FigureTranslation).join(
                newest,
                (FigureTranslation.object_id == newest.c.object_id)
                & (FigureTranslation.image_index == newest.c.image_index)
                & (FigureTranslation.version == newest.c.version),
            )
        )

        return {(row.object_id, row.image_index): row for row in rows}

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _master(self, chapter_id: uuid.UUID) -> ChapterMaster | None:
        found: ChapterMaster | None = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )

        return found

    async def _glossary(self, chapter: Chapter) -> Glossary:
        version = await TerminologyGate(self._session, self._context).effective(
            chapter.book_id, chapter.id
        )
        if version is None:
            return Glossary([])

        return await GlossaryService(self._session, self._context).load_version(version.id)

    async def _read(self, key: str) -> bytes:
        parts = [chunk async for chunk in self._storage.stream(key)]

        return b"".join(parts)
