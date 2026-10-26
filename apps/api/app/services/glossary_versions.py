"""Версии глоссария: сборка снимка, утверждение, просмотр.

Черновик — это снимок рабочего словаря книги в момент сборки, вместе с
тем, по каким версиям мастера глав он собран, чем отличается от
действующей версии и какие блоки эти отличия задевают. Утверждают ровно
то, что видели: черновик не пересобирается при утверждении, а если с
момента сборки изменился текст глав или утвердили другую версию, его
собирают заново.

Утверждение книжной версии заменяет и прежнюю книжную, и все главные
версии этой книги: книжная версия — решение о единообразии, и главы с
собственными решениями после неё снова разъехались бы. Утверждение главной
заменяет только прежнюю версию той же главы.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, or_, select, true

from app.models.block import Block, BlockKind
from app.models.chapter import Chapter
from app.models.coding import CodeKind
from app.models.glossary_version import (
    GlossaryVersion,
    GlossaryVersionChange,
    GlossaryVersionImpact,
    GlossaryVersionStatus,
    GlossaryVersionTerm,
)
from app.models.master import ChapterMaster
from app.models.organization import Role
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.books import BookService
from app.services.coding import CodeAllocator
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.glossary import EDITING_ROLES, GlossaryService
from app.services.search import ESCAPE, contains
from app.services.term_impact import Change, Entry, TextBlock, affected, checksum, diff, entry_of
from app.services.terminology_gate import GateItem, TerminologyGate

# Утверждает терминологию тот, кто отвечает за приёмку, — не тот, кто её
# готовит: переводчик собирает черновик, решение за менеджером.
APPROVING_ROLES = (Role.ADMIN, Role.MANAGER)

# Основание решения «терминов нет» — не формальность: по нему через год
# объясняют, почему книга переводилась без глоссария.
REASON_MIN = 10
REASON_MAX = 1000


@dataclass(frozen=True, slots=True)
class TermPage:
    total: int
    items: list[GlossaryVersionTerm]


@dataclass(frozen=True, slots=True)
class ChangeView:
    change: GlossaryVersionChange
    # Сколько блоков задевает изменение.
    blocks: int


@dataclass(frozen=True, slots=True)
class ImpactedBlock:
    block: Block
    chapter: Chapter
    # Какие изменения версии задевают этот блок — исходными написаниями.
    terms: list[str]


@dataclass(frozen=True, slots=True)
class ImpactPage:
    total: int
    items: list[ImpactedBlock]


@dataclass(frozen=True, slots=True)
class VersionView:
    """Версия и то, что о ней надо знать до решения."""

    version: GlossaryVersion
    chapter: Chapter | None
    # Что мешает утвердить — только у черновика.
    blockers: list[GateItem]
    changes: int
    impacted: int


class GlossaryVersionService(TenantService):
    async def of_book(self, book_id: uuid.UUID) -> list[GlossaryVersion]:
        """Версии книги, новые первыми."""
        book = await BookService(self._session, self._context).get(book_id)

        return list(
            await self._session.scalars(
                self.scoped(GlossaryVersion)
                .where(GlossaryVersion.book_id == book.id)
                .order_by(GlossaryVersion.number.desc())
            )
        )

    async def get(self, version_id: uuid.UUID) -> GlossaryVersion:
        version = await self._session.scalar(
            self.scoped(GlossaryVersion).where(GlossaryVersion.id == version_id)
        )

        if version is None:
            raise NotFoundError("Версия глоссария не найдена")

        return version

    async def view(self, version_id: uuid.UUID) -> VersionView:
        version = await self.get(version_id)
        chapter = None

        if version.chapter_id is not None:
            chapter = await self._session.scalar(
                self.scoped(Chapter).where(Chapter.id == version.chapter_id)
            )

        blockers = (
            await TerminologyGate(self._session, self._context).approval_blockers(version)
            if version.status is GlossaryVersionStatus.DRAFT
            else []
        )

        return VersionView(
            version=version,
            chapter=chapter,
            blockers=blockers,
            changes=await self._count_changes(version.id),
            impacted=await self._count_impacted(version.id),
        )

    async def create_draft(
        self, book_id: uuid.UUID, *, chapter_id: uuid.UUID | None = None
    ) -> GlossaryVersion:
        """Собрать черновик версии для книги или одной главы.

        Прежний черновик той же области заменяется: два черновика одной
        области — два ответа на один вопрос.
        """
        self._context.require(*EDITING_ROLES)

        # Сборка и утверждение версий книги идут по очереди: черновик,
        # собранный против версии, которую в эту же секунду заменили,
        # описывал бы отличия от того, что уже не действует.
        book = await BookService(self._session, self._context).lock(book_id)
        gate = TerminologyGate(self._session, self._context)

        if chapter_id is None:
            chapters = await gate.chapters(book.id)

            if not chapters:
                raise ConflictError("У книги ещё нет глав — сначала разметьте её структуру")
        else:
            chapter = await self._session.scalar(
                self.scoped(Chapter).where(Chapter.id == chapter_id, Chapter.book_id == book.id)
            )

            if chapter is None:
                raise NotFoundError("Глава не найдена")

            chapters = [chapter]

        masters = await gate.current_masters([chapter.id for chapter in chapters])
        rows = await GlossaryService(self._session, self._context).own_terms(
            project_id=book.project_id,
            source_language=book.source_language,
            target_language=book.target_language,
        )
        entries = [entry_of(row) for row in rows]

        base = await gate.effective(book.id, chapter_id)
        changes = diff(await self._entries(base.id), entries) if base is not None else []

        version = GlossaryVersion(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=book.id,
            chapter_id=chapter_id,
            number=await CodeAllocator(self._session, self._context).next(
                CodeKind.GLOSSARY_VERSION, book.id
            ),
            status=GlossaryVersionStatus.DRAFT,
            base_id=None if base is None else base.id,
            checksum=checksum(entries),
            term_count=len(entries),
            basis=[
                {
                    "chapter_id": str(chapter.id),
                    "master_id": str(masters[chapter.id].id) if chapter.id in masters else None,
                }
                for chapter in chapters
            ],
            created_by_id=self._context.user.id,
        )

        # Прежний черновик уходит до того, как встанет новый: уникальный
        # индекс «один черновик на область» проверяется на каждой строке.
        replaced = await self._session.scalar(
            self.scoped(GlossaryVersion).where(
                GlossaryVersion.book_id == book.id,
                GlossaryVersion.chapter_id.is_(None)
                if chapter_id is None
                else GlossaryVersion.chapter_id == chapter_id,
                GlossaryVersion.status == GlossaryVersionStatus.DRAFT,
            )
        )
        if replaced is not None:
            replaced.status = GlossaryVersionStatus.SUPERSEDED
            await self._session.flush()

        self._session.add(version)
        await self._session.flush()

        if replaced is not None:
            replaced.superseded_by_id = version.id

        self._session.add_all(
            GlossaryVersionTerm(
                organization_id=self.organization_id,
                version_id=version.id,
                term_id=row.id,
                source_term=row.source_term,
                source_term_normalized=row.source_term_normalized,
                target_term=row.target_term,
                allowed_variants=list(row.allowed_variants),
                kind=row.kind,
                status=row.status,
                mandatory=row.mandatory,
                case_sensitive=row.case_sensitive,
                first_use_rule=row.first_use_rule,
                domain=row.domain,
                note=row.note,
                reference=row.reference,
            )
            for row in rows
        )

        impacted = await self._record_changes(version, changes, list(masters.values()))

        AuditService(self._session, self._context).record(
            kind="glossary.version_drafted",
            subject_type="glossary_version",
            subject_id=version.id,
            payload={
                "book_id": str(book.id),
                "chapter_id": None if chapter_id is None else str(chapter_id),
                "number": version.number,
                "checksum": version.checksum,
                "terms": version.term_count,
                "base_id": None if base is None else str(base.id),
                "changes": len(changes),
                "impacted_blocks": impacted,
                "replaced_id": None if replaced is None else str(replaced.id),
            },
        )

        await self._session.commit()
        await self._session.refresh(version)

        return version

    async def approve(
        self, version_id: uuid.UUID, *, empty_reason: str | None = None
    ) -> GlossaryVersion:
        """Утвердить черновик — с этого момента по нему переводят.

        Пустую версию утверждают только с основанием: «терминов нет» — это
        решение, и оно записывается так же, как любое другое.
        """
        self._context.require(*APPROVING_ROLES)

        found = await self.get(version_id)
        book = await BookService(self._session, self._context).lock(found.book_id)
        # Перечитать под блокировкой книги: пока ждали её, черновик мог
        # быть заменён или утверждён другим запросом.
        version = await self._session.scalar(
            self.scoped(GlossaryVersion)
            .where(GlossaryVersion.id == found.id)
            .execution_options(populate_existing=True)
        )
        assert version is not None  # noqa: S101 — версия не удаляется, книга под блокировкой

        if version.status is not GlossaryVersionStatus.DRAFT:
            raise ConflictError("Утверждается только черновик версии")

        # Сначала то, что держит черновик: основание к пустой версии,
        # собранной до решения по кандидатам, ничего не исправит.
        blockers = await TerminologyGate(self._session, self._context).approval_blockers(version)
        if blockers:
            raise ConflictError("Утвердить нельзя: " + "; ".join(item.message for item in blockers))

        reason = (empty_reason or "").strip() or None

        if version.term_count == 0:
            if reason is None or len(reason) < REASON_MIN:
                raise InvalidInputError(
                    "Пустую версию утверждают с основанием: почему у книги нет терминов "
                    f"(не короче {REASON_MIN} знаков)"
                )
            if len(reason) > REASON_MAX:
                raise InvalidInputError(f"Основание длиннее {REASON_MAX} знаков")
        elif reason is not None:
            raise InvalidInputError("Основание «терминов нет» нужно только пустой версии")

        # Заменяемые уходят до утверждения новой: уникальный индекс «одна
        # утверждённая на область» проверяется на каждой строке.
        # Книжная версия заменяет все версии книги, главная — только
        # версию своей главы.
        scope: ColumnElement[bool] = (
            true()
            if version.chapter_id is None
            else GlossaryVersion.chapter_id == version.chapter_id
        )
        replaced = list(
            await self._session.scalars(
                self.scoped(GlossaryVersion).where(
                    GlossaryVersion.book_id == book.id,
                    GlossaryVersion.status == GlossaryVersionStatus.APPROVED,
                    scope,
                )
            )
        )

        for previous in replaced:
            previous.status = GlossaryVersionStatus.SUPERSEDED
            previous.superseded_by_id = version.id

        await self._session.flush()

        version.status = GlossaryVersionStatus.APPROVED
        version.approved_by_id = self._context.user.id
        version.approved_at = datetime.now(UTC)
        version.empty_reason = reason

        AuditService(self._session, self._context).record(
            kind="glossary.version_approved",
            subject_type="glossary_version",
            subject_id=version.id,
            payload={
                "book_id": str(book.id),
                "chapter_id": None if version.chapter_id is None else str(version.chapter_id),
                "number": version.number,
                "checksum": version.checksum,
                "terms": version.term_count,
                "empty_reason": reason,
                "superseded": [str(previous.id) for previous in replaced],
                "decided_by": "user",
            },
        )

        await self._session.commit()
        await self._session.refresh(version)

        return version

    async def terms(
        self,
        version_id: uuid.UUID,
        *,
        query: str | None = None,
        mandatory: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TermPage:
        version = await self.get(version_id)
        statement = self.scoped(GlossaryVersionTerm).where(
            GlossaryVersionTerm.version_id == version.id
        )

        if query:
            pattern = contains(query)
            statement = statement.where(
                or_(
                    GlossaryVersionTerm.source_term_normalized.ilike(pattern, escape=ESCAPE),
                    GlossaryVersionTerm.target_term.ilike(pattern, escape=ESCAPE),
                )
            )

        if mandatory is not None:
            statement = statement.where(GlossaryVersionTerm.mandatory.is_(mandatory))

        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = await self._session.scalars(
            statement.order_by(GlossaryVersionTerm.source_term_normalized)
            .limit(limit)
            .offset(offset)
        )

        return TermPage(total=int(total or 0), items=list(rows))

    async def changes(self, version_id: uuid.UUID) -> list[ChangeView]:
        version = await self.get(version_id)
        counted = await self._session.execute(
            select(GlossaryVersionImpact.change_id, func.count())
            .join(
                GlossaryVersionChange,
                GlossaryVersionChange.id == GlossaryVersionImpact.change_id,
            )
            .where(
                GlossaryVersionChange.organization_id == self.organization_id,
                GlossaryVersionChange.version_id == version.id,
            )
            .group_by(GlossaryVersionImpact.change_id)
        )
        # Перебором, а не `dict(...)`: у результата запроса есть `keys()`, и
        # `dict` принял бы его за словарь имён колонок.
        counts = {change_id: count for change_id, count in counted.tuples()}
        rows = await self._session.scalars(
            self.scoped(GlossaryVersionChange)
            .where(GlossaryVersionChange.version_id == version.id)
            .order_by(GlossaryVersionChange.source_term_normalized)
        )

        return [ChangeView(change=row, blocks=counts.get(row.id, 0)) for row in rows]

    async def impact(
        self,
        version_id: uuid.UUID,
        *,
        change_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ImpactPage:
        """Затронутые блоки версии — по главам и месту в главе."""
        version = await self.get(version_id)
        where = [
            GlossaryVersionChange.organization_id == self.organization_id,
            GlossaryVersionChange.version_id == version.id,
        ]

        if change_id is not None:
            where.append(GlossaryVersionChange.id == change_id)

        blocks = (
            select(GlossaryVersionImpact.block_id)
            .join(
                GlossaryVersionChange, GlossaryVersionChange.id == GlossaryVersionImpact.change_id
            )
            .where(*where)
            .distinct()
        )

        total = await self._session.scalar(select(func.count()).select_from(blocks.subquery()))
        rows = (
            await self._session.execute(
                select(Block, Chapter)
                .join(Chapter, Chapter.id == Block.chapter_id)
                .where(Block.organization_id == self.organization_id, Block.id.in_(blocks))
                .order_by(Chapter.ordinal, Block.ordinal)
                .limit(limit)
                .offset(offset)
            )
        ).tuples()
        page = list(rows)

        terms: dict[uuid.UUID, list[str]] = {}
        if page:
            for block_id, source in (
                await self._session.execute(
                    select(GlossaryVersionImpact.block_id, GlossaryVersionChange.source_term)
                    .join(
                        GlossaryVersionChange,
                        GlossaryVersionChange.id == GlossaryVersionImpact.change_id,
                    )
                    .where(*where, GlossaryVersionImpact.block_id.in_([b.id for b, _ in page]))
                    .order_by(GlossaryVersionChange.source_term_normalized)
                )
            ).tuples():
                terms.setdefault(block_id, []).append(source)

        return ImpactPage(
            total=int(total or 0),
            items=[
                ImpactedBlock(block=block, chapter=chapter, terms=terms.get(block.id, []))
                for block, chapter in page
            ],
        )

    async def _record_changes(
        self, version: GlossaryVersion, changes: list[Change], masters: list[ChapterMaster]
    ) -> int:
        """Записать отличия и затронутые блоки; вернуть число блоков."""
        if not changes:
            return 0

        ids = [uuid.UUID(value) for master in masters for value in master.block_ids]
        # Листинги переносятся побайтно и не переводятся — термин в коде
        # перевода не задевает.
        blocks = (
            list(
                await self._session.scalars(
                    self.scoped(Block).where(Block.id.in_(ids), Block.kind != BlockKind.CODE)
                )
            )
            if ids
            else []
        )
        hits = affected([TextBlock(block.id, block.source_text) for block in blocks], changes)
        touched: set[uuid.UUID] = set()

        for change, found in zip(changes, hits, strict=True):
            record = GlossaryVersionChange(
                id=uuid.uuid4(),
                organization_id=self.organization_id,
                version_id=version.id,
                source_term=change.entry.source_term,
                source_term_normalized=change.entry.source_term_normalized,
                kind=change.kind,
                before=None if change.before is None else change.before.record(),
                after=None if change.after is None else change.after.record(),
            )
            self._session.add(record)
            self._session.add_all(
                GlossaryVersionImpact(
                    organization_id=self.organization_id, change_id=record.id, block_id=block_id
                )
                for block_id in found
            )
            touched.update(found)

        await self._session.flush()

        return len(touched)

    async def _entries(self, version_id: uuid.UUID) -> list[Entry]:
        rows = await self._session.scalars(
            self.scoped(GlossaryVersionTerm).where(GlossaryVersionTerm.version_id == version_id)
        )

        return [entry_of(row) for row in rows]

    async def _count_changes(self, version_id: uuid.UUID) -> int:
        counted = await self._session.scalar(
            select(func.count()).where(
                GlossaryVersionChange.organization_id == self.organization_id,
                GlossaryVersionChange.version_id == version_id,
            )
        )

        return int(counted or 0)

    async def _count_impacted(self, version_id: uuid.UUID) -> int:
        counted = await self._session.scalar(
            select(func.count(func.distinct(GlossaryVersionImpact.block_id)))
            .join(
                GlossaryVersionChange, GlossaryVersionChange.id == GlossaryVersionImpact.change_id
            )
            .where(
                GlossaryVersionChange.organization_id == self.organization_id,
                GlossaryVersionChange.version_id == version_id,
            )
        )

        return int(counted or 0)
