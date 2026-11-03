"""Решения по регрессии: применить исправление к повторам, отметить, завести дочернее замечание.

Исправление не расходится по книге само. Человек видит затронутые места и решает: повтору — то же
исправление новой редакцией, другому месту — «не затронуто» или своё замечание. Когда решены все
обязательные места, прогон завершён, и замечание можно закрывать.

Применение идёт целиком или никак: если у какого-то повтора текст уже сменился, решение принималось
о другом тексте, и его надо посмотреть заново. Кандидат в финальный текст без отдельного решения не
перезаписывается: это уже проверенная редакция.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book_object import BookObject
from app.models.chapter import Chapter
from app.models.issue import Issue, IssueCategory, IssueSeverity
from app.models.regression import (
    RegressionDecision,
    RegressionItem,
    RegressionRun,
    RegressionStatus,
)
from app.models.translation import RevisionOrigin, RevisionStage, TranslationRevision
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.issues import REGISTERING_ROLES, IssueService
from app.services.storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class ItemRow:
    item: RegressionItem
    code: str
    source_text: str | None
    current_text: str | None
    # Сюда уже поставлен кандидат в финальный текст: без отдельного решения не перезаписываем.
    final_candidate: bool
    child_code: str | None


@dataclass(frozen=True, slots=True)
class RegressionView:
    run: RegressionRun
    items: list[ItemRow]

    @property
    def pending(self) -> int:
        return sum(
            1
            for row in self.items
            if row.item.required and row.item.decision is RegressionDecision.PENDING
        )


class RegressionService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def of_issue(self, issue_id: uuid.UUID) -> RegressionView | None:
        """Последний прогон замечания со всеми местами."""
        run = await self._session.scalar(
            self.scoped(RegressionRun)
            .where(RegressionRun.issue_id == issue_id)
            .order_by(RegressionRun.created_at.desc())
            .limit(1)
        )
        if run is None:
            return None

        return await self._view(run)

    async def apply(
        self,
        run_id: uuid.UUID,
        *,
        item_ids: Sequence[uuid.UUID],
        overwrite_final: bool = False,
        note: str | None = None,
    ) -> RegressionView:
        """Применить исправление к выбранным повторам: каждому своя новая редакция."""
        self._context.require(*REGISTERING_ROLES)

        if not item_ids:
            raise InvalidInputError("Не выбрано ни одного места")

        text_note = (note or "").strip() or None

        if overwrite_final and text_note is None:
            raise InvalidInputError("Напишите, почему перезаписываем кандидат в финальный текст")

        run = await self._open_run(run_id)
        items = list(
            await self._session.scalars(
                self.scoped(RegressionItem).where(
                    RegressionItem.run_id == run.id, RegressionItem.id.in_(item_ids)
                )
            )
        )
        if len(items) != len(set(item_ids)):
            raise NotFoundError("Такого места в этом прогоне нет")

        for item in items:
            if item.proposed_text is None or item.block_id is None:
                raise ConflictError("Исправление можно применить только к повтору того же текста")
            if item.decision is not RegressionDecision.PENDING:
                raise ConflictError("По этому месту решение уже принято")

        blocks = {
            block.id: block
            for block in await self._session.scalars(
                self.scoped(Block)
                .where(Block.id.in_([item.block_id for item in items]))
                .order_by(Block.id)
                .with_for_update()
            )
        }
        currents = {
            revision.id: revision
            for revision in await self._session.scalars(
                self.scoped(TranslationRevision).where(
                    TranslationRevision.id.in_(
                        [
                            block.current_revision_id
                            for block in blocks.values()
                            if block.current_revision_id is not None
                        ]
                    )
                )
            )
        }

        # Сначала проверить всё, потом записывать: применение идёт целиком или никак.
        for item in items:
            block = blocks[item.block_id]  # type: ignore[index]

            if block.current_revision_id != item.base_revision_id:
                raise ConflictError(
                    f"Текст блока {block.code} изменился после расчёта: посмотрите его заново"
                )

            current = currents.get(block.current_revision_id)  # type: ignore[arg-type]

            if (
                current is not None
                and current.stage is RevisionStage.FINAL_CANDIDATE
                and not overwrite_final
            ):
                raise ConflictError(
                    f"В блоке {block.code} уже кандидат в финальный текст: нужно отдельное решение"
                )

        numbers = await self._next_numbers([block.id for block in blocks.values()])

        for item in items:
            block = blocks[item.block_id]  # type: ignore[index]
            revision = TranslationRevision(
                id=uuid.uuid4(),
                organization_id=self.organization_id,
                block_id=block.id,
                revision_no=numbers[block.id],
                stage=RevisionStage.WORKING,
                origin=RevisionOrigin.HUMAN,
                text=item.proposed_text,
                supersedes_id=block.current_revision_id,
                created_by_id=self._context.user.id,
            )
            self._session.add(revision)
            await self._session.flush()

            block.current_revision_id = revision.id
            item.decision = RegressionDecision.PROPAGATED
            item.applied_revision_id = revision.id
            item.decided_by_id = self._context.user.id
            item.note = text_note

        AuditService(self._session, self._context).record(
            kind="regression.propagated",
            subject_type="regression_run",
            subject_id=run.id,
            payload={
                "items": [str(item.id) for item in items],
                "overwrite_final": overwrite_final,
                "note": text_note,
            },
        )

        return await self._finish(run)

    async def decide(
        self,
        item_id: uuid.UUID,
        *,
        affected: bool,
        note: str | None,
        category: IssueCategory | None = None,
        severity: IssueSeverity | None = None,
    ) -> RegressionView:
        """Место посмотрели: не затронуто либо здесь своя проблема и своё замечание."""
        self._context.require(*REGISTERING_ROLES)

        item = await self._session.scalar(
            self.scoped(RegressionItem).where(RegressionItem.id == item_id).with_for_update()
        )
        if item is None:
            raise NotFoundError("Такого места нет")

        run = await self._open_run(item.run_id)

        if item.decision is not RegressionDecision.PENDING:
            raise ConflictError("По этому месту решение уже принято")

        text_note = (note or "").strip() or None

        if affected:
            if text_note is None or category is None or severity is None:
                raise InvalidInputError("Для замечания нужны описание, категория и серьёзность")

            child, _ = await IssueService(self._session, self._context, self._storage).file(
                block_id=item.block_id,
                object_id=item.object_id if item.block_id is None else None,
                category=category,
                severity=severity,
                description=text_note,
                parent_issue_id=run.issue_id,
            )
            item.child_issue_id = child.id
            item.decision = RegressionDecision.ISSUE_CREATED
        else:
            item.decision = RegressionDecision.NOT_AFFECTED

        item.decided_by_id = self._context.user.id
        item.note = text_note

        AuditService(self._session, self._context).record(
            kind="regression.decided",
            subject_type="regression_item",
            subject_id=item.id,
            payload={"decision": item.decision.value, "note": text_note},
        )

        return await self._finish(run)

    # ── внутреннее ──

    async def _finish(self, run: RegressionRun) -> RegressionView:
        """Завершить прогон, если все обязательные места решены, и зафиксировать."""
        await self._session.flush()

        pending = await self._session.scalar(
            select(func.count())
            .select_from(RegressionItem)
            .where(
                RegressionItem.run_id == run.id,
                RegressionItem.required.is_(True),
                RegressionItem.decision == RegressionDecision.PENDING,
            )
        )

        if not pending:
            run.status = RegressionStatus.COMPLETED

        await self._session.commit()
        await self._session.refresh(run)

        return await self._view(run)

    async def _open_run(self, run_id: uuid.UUID) -> RegressionRun:
        run = await self._session.scalar(
            self.scoped(RegressionRun).where(RegressionRun.id == run_id).with_for_update()
        )
        if run is None:
            raise NotFoundError("Прогон регрессии не найден")
        if run.status is RegressionStatus.SUPERSEDED:
            raise ConflictError("Замечание открыли заново: этот прогон уже не про нынешний текст")

        return run

    async def _next_numbers(self, block_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        rows = await self._session.execute(
            select(TranslationRevision.block_id, func.max(TranslationRevision.revision_no))
            .where(TranslationRevision.block_id.in_(block_ids))
            .group_by(TranslationRevision.block_id)
        )
        known = {row[0]: int(row[1]) for row in rows.all()}

        return {block_id: known.get(block_id, 0) + 1 for block_id in block_ids}

    async def _view(self, run: RegressionRun) -> RegressionView:
        items = list(
            await self._session.scalars(
                self.scoped(RegressionItem)
                .where(RegressionItem.run_id == run.id)
                .order_by(RegressionItem.required.desc(), RegressionItem.kind, RegressionItem.id)
            )
        )

        blocks = await self._load(Block, {i.block_id for i in items if i.block_id is not None})
        objects = await self._load(
            BookObject, {i.object_id for i in items if i.object_id is not None}
        )
        chapters = await self._load(
            Chapter,
            {b.chapter_id for b in blocks.values()} | {o.chapter_id for o in objects.values()},
        )
        revisions = await self._load(
            TranslationRevision,
            {b.current_revision_id for b in blocks.values() if b.current_revision_id is not None},
        )
        children = await self._load(
            Issue, {i.child_issue_id for i in items if i.child_issue_id is not None}
        )

        rows = []
        for item in items:
            block = blocks.get(item.block_id) if item.block_id is not None else None
            target = objects.get(item.object_id) if item.object_id is not None else None
            owner = block or target
            prefix = chapters[owner.chapter_id].code if owner is not None else None
            code = owner.code if owner is not None else ""
            current = (
                revisions.get(block.current_revision_id)
                if block is not None and block.current_revision_id is not None
                else None
            )

            rows.append(
                ItemRow(
                    item=item,
                    code=f"{prefix}-{code}" if prefix is not None else code,
                    source_text=block.source_text if block is not None else None,
                    current_text=current.text if current is not None else None,
                    final_candidate=(
                        current is not None and current.stage is RevisionStage.FINAL_CANDIDATE
                    ),
                    child_code=(
                        children[item.child_issue_id].code
                        if item.child_issue_id is not None
                        else None
                    ),
                )
            )

        # Сначала обязательное, внутри вида — по коду: порядок не должен плавать.
        rows.sort(key=lambda row: (not row.item.required, row.item.kind.value, row.code))

        return RegressionView(run=run, items=rows)

    async def _load(self, model, ids: set[uuid.UUID]) -> dict:  # type: ignore[no-untyped-def, type-arg]
        if not ids:
            return {}

        rows = await self._session.scalars(self.scoped(model).where(model.id.in_(ids)))

        return {row.id: row for row in rows}
