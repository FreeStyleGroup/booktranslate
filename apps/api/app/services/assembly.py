"""Сборка книги из утверждённых версий глав.

«Последняя» допустима только как подсказка при выборе. Выпуск называет версии глав явно, поэтому
его состав не меняется сам по себе. Сборка с тем же составом не плодит новую версию, а возвращает
прежнюю: манифест совпал, значит это тот же выпуск.

Расхождения двух родов. Блокирующие выпуск невозможен: глава пропущена, стоит дважды, не
утверждена, ссылка ведёт мимо состава. Предупреждения собрать не мешают: нумерация и подписи
объектов приходят из самой книги, и исправить их значило бы переписать оригинал.

Вводная часть и приложения отдельной сущностью не заводятся: в разборе книги это те же главы, с
той же версией и тем же манифестом."""

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.block import Block, BlockKind
from app.models.book import BookEdition
from app.models.book_object import BookObject, ObjectReference
from app.models.chapter import Chapter
from app.models.organization import Role
from app.models.release import (
    BookRelease,
    BookReleaseChapter,
    BookReleaseStatus,
    ChapterRelease,
    ReleaseStatus,
)
from app.models.translation import TranslationRevision
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.canonical import revision_set_hash
from app.services.chapter_releases import MANIFEST_SCHEMA, hash_manifest
from app.services.errors import ConflictError, NotFoundError

BUILDING_ROLES = (Role.ADMIN, Role.MANAGER)

BLOCKER = "blocker"
WARNING = "warning"

# Глубже в оглавление книги не заходим: подразделы ему только мешают.
TOC_LEVELS = 2


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    severity: str
    message: str
    chapter_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class PlanItem:
    chapter: Chapter
    chosen: ChapterRelease | None
    available: list[ChapterRelease]
    # Рабочий текст главы ушёл вперёд от выбранной версии.
    working_differs: bool


@dataclass(slots=True)
class Plan:
    book: BookEdition
    items: list[PlanItem]
    problems: list[Problem] = field(default_factory=list)
    toc: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not any(item.severity == BLOCKER for item in self.problems)

    @property
    def chosen(self) -> list[ChapterRelease]:
        return [item.chosen for item in self.items if item.chosen is not None]


class AssemblyService(TenantService):
    async def plan(self, book_id: uuid.UUID, chosen_ids: Sequence[uuid.UUID] | None = None) -> Plan:
        """Что соберётся и что этому мешает. Без выбора берётся последняя утверждённая версия."""
        book = await self._book(book_id)
        chapters = list(
            await self._session.scalars(
                self.scoped(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.ordinal)
            )
        )
        releases = list(
            await self._session.scalars(
                self.scoped(ChapterRelease)
                .where(ChapterRelease.book_id == book.id)
                .order_by(ChapterRelease.version_major.desc(), ChapterRelease.version_minor.desc())
            )
        )
        by_chapter: dict[uuid.UUID, list[ChapterRelease]] = {}
        for release in releases:
            by_chapter.setdefault(release.chapter_id, []).append(release)

        problems: list[Problem] = []
        order = {chapter.id: chapter.ordinal for chapter in chapters}
        chosen: dict[uuid.UUID, ChapterRelease] = {}

        if chosen_ids is None:
            for chapter_id, rows in by_chapter.items():
                approved = [row for row in rows if row.status is ReleaseStatus.APPROVED]
                if approved:
                    chosen[chapter_id] = approved[0]
        else:
            chosen = self._apply_choice(chosen_ids, releases, order, problems)

        items = await self._items(chapters, chosen, by_chapter, problems)
        plan = Plan(book=book, items=items, problems=problems)

        self._check_numbering(plan)
        await self._check_references(plan)
        await self._check_objects(plan)
        await self._fill_toc(plan)

        return plan

    async def build(
        self, book_id: uuid.UUID, chosen_ids: Sequence[uuid.UUID], *, major: bool = False
    ) -> tuple[BookRelease, bool]:
        """Собрать выпуск. Второе значение ложно, если такой состав уже был собран."""
        self._context.require(*BUILDING_ROLES)

        # Блокировка книги: две одновременные сборки получили бы один номер версии.
        book = await self._session.scalar(
            self.scoped(BookEdition).where(BookEdition.id == book_id).with_for_update()
        )
        if book is None:
            raise NotFoundError("Книга не найдена")

        plan = await self.plan(book.id, chosen_ids)
        if not plan.ready:
            raise ConflictError(
                "Собрать нельзя: "
                + "; ".join(item.message for item in plan.problems if item.severity == BLOCKER)
            )
        if not plan.chosen:
            raise ConflictError("В выпуске нет ни одной главы")

        manifest = _manifest(plan)
        digest = hash_manifest(manifest)

        same = await self._session.scalar(
            self.scoped(BookRelease).where(
                BookRelease.book_id == book.id, BookRelease.manifest_hash == digest
            )
        )
        if same is not None:
            return same, False

        latest = await self._session.scalar(
            self.scoped(BookRelease)
            .where(BookRelease.book_id == book.id)
            .order_by(BookRelease.version_major.desc(), BookRelease.version_minor.desc())
            .limit(1)
        )
        if latest is None:
            version = (1, 0)
        elif major:
            version = (latest.version_major + 1, 0)
        else:
            version = (latest.version_major, latest.version_minor + 1)

        release = BookRelease(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=book.id,
            version_major=version[0],
            version_minor=version[1],
            code=f"{book.code}-RELEASE-v{version[0]}.{version[1]}",
            status=BookReleaseStatus.BUILT,
            manifest=manifest,
            manifest_hash=digest,
            created_by_id=self._context.user.id,
        )

        try:
            async with self._session.begin_nested():
                self._session.add(release)
                await self._session.flush()

                for position, chapter_release in enumerate(plan.chosen, start=1):
                    self._session.add(
                        BookReleaseChapter(
                            organization_id=self.organization_id,
                            release_id=release.id,
                            chapter_release_id=chapter_release.id,
                            position=position,
                        )
                    )
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Выпуск уже собирают: обновите страницу") from error

        AuditService(self._session, self._context).record(
            kind="book_release.built",
            subject_type="book_release",
            subject_id=release.id,
            payload={"code": release.code, "manifest_hash": digest},
        )
        await self._session.commit()
        await self._session.refresh(release)

        return release, True

    async def of_book(self, book_id: uuid.UUID) -> list[BookRelease]:
        book = await self._book(book_id)
        rows = await self._session.scalars(
            self.scoped(BookRelease)
            .where(BookRelease.book_id == book.id)
            .order_by(BookRelease.version_major.desc(), BookRelease.version_minor.desc())
        )

        return list(rows)

    async def get(self, release_id: uuid.UUID) -> BookRelease:
        release = await self._session.scalar(
            self.scoped(BookRelease).where(BookRelease.id == release_id)
        )
        if release is None:
            raise NotFoundError("Такого выпуска нет")

        return release

    # ── внутреннее ──

    def _apply_choice(
        self,
        chosen_ids: Sequence[uuid.UUID],
        releases: Sequence[ChapterRelease],
        order: dict[uuid.UUID, int],
        problems: list[Problem],
    ) -> dict[uuid.UUID, ChapterRelease]:
        known = {row.id: row for row in releases}
        chosen: dict[uuid.UUID, ChapterRelease] = {}
        last = -1

        for release_id in chosen_ids:
            release = known.get(release_id)

            if release is None:
                problems.append(
                    Problem("foreign_release", BLOCKER, "Выбрана версия не из этой книги")
                )
                continue
            if release.chapter_id in chosen:
                problems.append(
                    Problem(
                        "duplicate_chapter",
                        BLOCKER,
                        f"Глава выбрана дважды: {release.code}",
                        release.chapter_id,
                    )
                )
                continue
            if release.status is not ReleaseStatus.APPROVED:
                problems.append(
                    Problem(
                        "draft_chapter",
                        BLOCKER,
                        f"Версия {release.code} не утверждена",
                        release.chapter_id,
                    )
                )

            ordinal = order[release.chapter_id]
            if ordinal < last:
                problems.append(
                    Problem(
                        "wrong_order",
                        BLOCKER,
                        f"Версия {release.code} стоит не на своём месте",
                        release.chapter_id,
                    )
                )
            last = ordinal
            chosen[release.chapter_id] = release

        return chosen

    async def _items(
        self,
        chapters: Sequence[Chapter],
        chosen: dict[uuid.UUID, ChapterRelease],
        by_chapter: dict[uuid.UUID, list[ChapterRelease]],
        problems: list[Problem],
    ) -> list[PlanItem]:
        items: list[PlanItem] = []

        for chapter in chapters:
            release = chosen.get(chapter.id)
            differs = False
            name = chapter.code or f"глава {chapter.ordinal}"

            if release is None:
                problems.append(
                    Problem(
                        "missing_chapter",
                        BLOCKER,
                        f"У главы {name} нет утверждённой финальной версии",
                        chapter.id,
                    )
                )
            else:
                differs = await self._working_differs(release)
                if differs:
                    problems.append(
                        Problem(
                            "working_differs",
                            WARNING,
                            f"Рабочий текст главы {name} новее версии {release.code}",
                            chapter.id,
                        )
                    )

            items.append(
                PlanItem(
                    chapter=chapter,
                    chosen=release,
                    available=[
                        row
                        for row in by_chapter.get(chapter.id, [])
                        if row.status is ReleaseStatus.APPROVED
                    ],
                    working_differs=differs,
                )
            )

        return items

    async def _working_differs(self, release: ChapterRelease) -> bool:
        rows = await self._session.execute(
            select(Block.id, Block.current_revision_id).where(
                Block.organization_id == self.organization_id,
                Block.chapter_id == release.chapter_id,
                Block.active.is_(True),
            )
        )

        return revision_set_hash([(row[0], row[1]) for row in rows.all()]) != (
            release.revision_set_hash
        )

    def _check_numbering(self, plan: Plan) -> None:
        numbers = [item.chapter.number for item in plan.items if item.chapter.number is not None]

        for before, after in zip(numbers, numbers[1:], strict=False):
            if after != before + 1:
                plan.problems.append(
                    Problem(
                        "numbering_gap",
                        WARNING,
                        f"В нумерации глав пропуск: после {before} идёт {after}",
                    )
                )

    async def _check_references(self, plan: Plan) -> None:
        """Ссылка на объект не должна вести за пределы выпуска."""
        block_ids = [
            uuid.UUID(row["id"]) for release in plan.chosen for row in release.manifest["blocks"]
        ]
        if not block_ids:
            return

        included = {
            uuid.UUID(row["id"]) for release in plan.chosen for row in release.manifest["objects"]
        }
        rows = await self._session.execute(
            select(ObjectReference.phrase, ObjectReference.object_id, Block.chapter_id)
            .join(Block, Block.id == ObjectReference.block_id)
            .where(
                ObjectReference.organization_id == self.organization_id,
                ObjectReference.block_id.in_(block_ids),
            )
            .order_by(ObjectReference.phrase)
        )

        for phrase, object_id, chapter_id in rows.all():
            if object_id not in included:
                plan.problems.append(
                    Problem(
                        "dangling_reference",
                        BLOCKER,
                        f"Ссылка «{phrase}» ведёт на объект вне выпуска",
                        chapter_id,
                    )
                )

    async def _check_objects(self, plan: Plan) -> None:
        ids = [
            uuid.UUID(row["id"]) for release in plan.chosen for row in release.manifest["objects"]
        ]
        if not ids:
            return

        rows = await self._session.scalars(
            self.scoped(BookObject).where(BookObject.id.in_(ids), BookObject.label.is_not(None))
        )
        labels = Counter((row.type.value, row.label) for row in rows)

        for (kind, label), count in sorted(labels.items()):
            if count > 1:
                plan.problems.append(
                    Problem(
                        "duplicate_object_label",
                        WARNING,
                        f"Подпись {label} встречается {count} раза у объектов вида «{kind}»",
                    )
                )

    async def _fill_toc(self, plan: Plan) -> None:
        """Оглавление из заголовков, которые вошли в выпуск, их утверждённым текстом."""
        for item in plan.items:
            release = item.chosen
            if release is None:
                continue

            revisions = {
                uuid.UUID(row["id"]): uuid.UUID(row["revision_id"])
                for row in release.manifest["blocks"]
            }
            headings = list(
                await self._session.scalars(
                    self.scoped(Block)
                    .where(Block.id.in_(revisions), Block.kind == BlockKind.HEADING)
                    .order_by(Block.ordinal)
                )
            )
            if not headings:
                plan.problems.append(
                    Problem(
                        "toc_no_heading",
                        WARNING,
                        f"В главе {item.chapter.code} нет заголовка: в оглавлении её название",
                        item.chapter.id,
                    )
                )
                plan.toc.append(
                    {
                        "chapter_code": item.chapter.code,
                        "level": 1,
                        "text": item.chapter.title or item.chapter.code,
                    }
                )
                continue

            texts = {
                row.id: row.text
                for row in await self._session.scalars(
                    self.scoped(TranslationRevision).where(
                        TranslationRevision.id.in_([revisions[b.id] for b in headings])
                    )
                )
            }
            for heading in headings:
                level = heading.source_location.get("level")
                level = level if isinstance(level, int) else 1

                if level <= TOC_LEVELS:
                    plan.toc.append(
                        {
                            "chapter_code": item.chapter.code,
                            "level": level,
                            "text": texts[revisions[heading.id]],
                        }
                    )

    async def _book(self, book_id: uuid.UUID) -> BookEdition:
        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))
        if book is None:
            raise NotFoundError("Книга не найдена")

        return book


def _manifest(plan: Plan) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "book_id": str(plan.book.id),
        "book_code": plan.book.code,
        "title": plan.book.title,
        "chapters": [
            {
                "position": position,
                "chapter_id": str(item.chapter.id),
                "chapter_code": item.chapter.code,
                "title": item.chapter.title,
                "release_id": str(item.chosen.id),
                "release_code": item.chosen.code,
                "manifest_hash": item.chosen.manifest_hash,
            }
            for position, item in enumerate(
                (row for row in plan.items if row.chosen is not None), start=1
            )
            if item.chosen is not None
        ],
        "toc": plan.toc,
    }
