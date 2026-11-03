"""Реестр ошибок: регистрация, решения по замечанию, отбор и статистика.

Замечание рождается со снимком того, что видел нашедший, и живёт только действиями: у каждого
действия свой адрес, свои права и своё условие. Произвольной смены статуса нет ни в API, ни
здесь: всё проходит через `_move`, а тот — через таблицу переходов.

Строка замечания блокируется на время решения. Без этого два проверяющих могли бы прочитать
одно и то же состояние и оба посчитать свой переход допустимым.

Правило двух человек включается настройкой пространства и касается только критичных: в
команде из одного редактора оно остановило бы работу, а новых ролей процесс не вводит.
"""

import enum
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block
from app.models.book import BookEdition
from app.models.book_object import BookObject, ObjectReference, ObjectType
from app.models.chapter import Chapter
from app.models.issue import (
    Issue,
    IssueAttachment,
    IssueCategory,
    IssueEvent,
    IssueEventKind,
    IssueSeverity,
    IssueStatus,
)
from app.models.organization import Membership, Role, User
from app.models.regression import (
    RegressionDecision,
    RegressionItem,
    RegressionRun,
    RegressionStatus,
)
from app.models.translation import RevisionOrigin, RevisionStage, TranslationRevision
from app.models.workspace import MemoryPublish, WorkspaceSettings
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.book_objects import ObjectService, own_blocks
from app.services.context import RequestContext
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.glossary import GlossaryService, Term
from app.services.issue_numbers import IssueNumberService
from app.services.issue_status import DECIDED, OPEN, can_transition, require_transition
from app.services.memory import HUMAN, TranslationMemory
from app.services.regression_graph import RegressionGraph
from app.services.search import ESCAPE, contains
from app.services.storage import ObjectStorage
from app.services.terminology_gate import TerminologyGate
from app.services.translation_runner import is_protected
from app.services.workspace import memory_publish_for

# Заметить ошибку может любой, кто работает с текстом.
REGISTERING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER)
# Решает тот, кто отвечает за качество: переводчик не судья собственному тексту.
DECIDING_ROLES = (Role.ADMIN, Role.MANAGER, Role.REVIEWER)
ARCHIVING_ROLES = (Role.ADMIN, Role.MANAGER)

SEVERITY_WEIGHT = {
    IssueSeverity.CRITICAL: 100,
    IssueSeverity.MAJOR: 30,
    IssueSeverity.MINOR: 5,
}
# В формуле, коде и таблице ошибка дороже: читатель перенесёт их в работу, не перепроверяя.
OBJECT_RISK = {
    ObjectType.EQUATION: 20,
    ObjectType.CODE: 20,
    ObjectType.TABLE: 15,
    ObjectType.FIGURE: 10,
}
# Потолок влияния ниже разрыва между разрядами: сотня повторов незначительной опечатки не
# должна оказаться в реестре выше критичной ошибки в одной формуле.
IMPACT_CEILING = 50

CONTEXT_BLOCKS = 2


class IssueSort(str, enum.Enum):
    PRIORITY = "priority"
    CREATED = "created"
    SEVERITY = "severity"
    STATUS = "status"


_SORT_COLUMNS = {
    IssueSort.PRIORITY: Issue.priority_score,
    IssueSort.CREATED: Issue.created_at,
    IssueSort.SEVERITY: Issue.severity,
    IssueSort.STATUS: Issue.status,
}


@dataclass(frozen=True, slots=True)
class IssueFilter:
    book_id: uuid.UUID | None = None
    chapter_id: uuid.UUID | None = None
    block_id: uuid.UUID | None = None
    object_id: uuid.UUID | None = None
    statuses: tuple[IssueStatus, ...] = ()
    severity: IssueSeverity | None = None
    category: IssueCategory | None = None
    assignee_id: uuid.UUID | None = None
    query: str | None = None
    # Архив не показывается, пока о нём не спросили, но и не исчезает.
    archived: bool = False


@dataclass(slots=True)
class IssueRow:
    """Замечание с тем, что нужно для строки реестра: без этого — десятки запросов на страницу."""

    issue: Issue
    book_title: str
    block_code: str | None
    object_code: str | None
    detected_by: str | None
    assignee: str | None


@dataclass(slots=True)
class IssuePage:
    total: int
    items: list[IssueRow]


@dataclass(slots=True)
class IssueStats:
    total: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    # То, что считает контроль выпуска: незакрытые критичные и серьёзные.
    open_critical: int = 0
    open_major: int = 0


@dataclass(frozen=True, slots=True)
class Neighbour:
    block: Block
    translation: str | None


@dataclass(frozen=True, slots=True)
class FixCandidate:
    """Редакция, которой можно закрыть замечание: текущая и появившаяся после находки."""

    revision: TranslationRevision
    block: Block


@dataclass(frozen=True, slots=True)
class LinkedObject:
    object: BookObject
    chapter_code: str | None


@dataclass(frozen=True, slots=True)
class EventRow:
    event: IssueEvent
    actor: str | None


@dataclass(slots=True)
class IssueView:
    """Всё, что нужно проверяющему, одним ответом."""

    row: IssueRow
    chapter: Chapter
    current: TranslationRevision | None
    block_active: bool
    context: list[Neighbour]
    terms: list[Term]
    objects: list[LinkedObject]
    events: list[EventRow]
    attachments: list[IssueAttachment]
    candidates: list[FixCandidate]
    # Какие блоки можно править по этому замечанию и что в них стоит сейчас.
    editable: list[FixCandidate]
    children: list[Issue]
    parent: Issue | None
    actions: list[str]
    # Почему решение за другим человеком; пусто — решать может и этот.
    review_note: str | None


class IssueService(TenantService):
    def __init__(
        self,
        session: AsyncSession,
        context: RequestContext,
        storage: ObjectStorage,
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    # ── регистрация ──

    async def register(
        self,
        *,
        block_id: uuid.UUID | None,
        object_id: uuid.UUID | None,
        category: IssueCategory,
        severity: IssueSeverity,
        description: str,
        proposed_fix: str | None = None,
        parent_issue_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
        automatic: bool = False,
    ) -> Issue:
        """Завести замечание и зафиксировать его."""
        issue, created = await self.file(
            block_id=block_id,
            object_id=object_id,
            category=category,
            severity=severity,
            description=description,
            proposed_fix=proposed_fix,
            parent_issue_id=parent_issue_id,
            assignee_id=assignee_id,
            dedupe_key=dedupe_key,
            automatic=automatic,
        )

        if created:
            await self._session.commit()
            await self._session.refresh(issue)

        return issue

    async def file(
        self,
        *,
        block_id: uuid.UUID | None,
        object_id: uuid.UUID | None,
        category: IssueCategory,
        severity: IssueSeverity,
        description: str,
        proposed_fix: str | None = None,
        parent_issue_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
        automatic: bool = False,
        qa_run_id: uuid.UUID | None = None,
    ) -> tuple[Issue, bool]:
        """Завести замечание на блок или объект; транзакцией управляет вызывающий.

        Код, снимки и редакцию подставляет сервер: клиент сообщает только, на что замечание и в
        чём оно. Повторная находка с тем же отпечатком возвращает прежнюю запись, и второе значение
        ответа говорит, новая ли это запись.
        """
        self._context.require(*REGISTERING_ROLES)

        text = description.strip()
        if not text:
            raise InvalidInputError("Опишите, в чём ошибка")

        if block_id is None and object_id is None:
            raise InvalidInputError("Замечание ставится на блок или объект")

        if dedupe_key is not None:
            known = await self._by_dedupe(dedupe_key)
            if known is not None:
                return known, False

        block = await self._block(block_id) if block_id is not None else None
        item = await self._object(object_id) if object_id is not None else None
        own = await self._own_blocks(item) if item is not None else []

        if block is not None and item is not None and block.id not in {b.id for b in own}:
            raise InvalidInputError("Блок не относится к этому объекту")

        chapter_id = block.chapter_id if block is not None else item.chapter_id  # type: ignore[union-attr]
        chapter = await self._chapter(chapter_id)
        book = await self._book(chapter.book_id)

        if parent_issue_id is not None:
            await self._parent(parent_issue_id, book.id)

        if assignee_id is not None:
            await self._require_member(assignee_id)

        subject = [block] if block is not None else own
        revisions = await self._revisions(b.current_revision_id for b in subject)
        impact = await self._impact(book.id, block) if block is not None else 1

        number, code = await IssueNumberService(self._session, self._context).allocate(
            book, chapter
        )
        issue = Issue(
            organization_id=self.organization_id,
            book_id=book.id,
            chapter_id=chapter.id,
            block_id=block.id if block is not None else None,
            object_id=item.id if item is not None else None,
            parent_issue_id=parent_issue_id,
            qa_run_id=qa_run_id,
            number=number,
            code=code,
            category=category,
            severity=severity,
            status=IssueStatus.NEW,
            priority_score=priority_of(severity, impact, item),
            impact_count=impact,
            automatic=automatic,
            detected_by_id=None if automatic else self._context.user.id,
            source_snapshot=_source_of(item, subject),
            target_snapshot=_target_of(subject, revisions),
            discovered_revision_id=block.current_revision_id if block is not None else None,
            discovered_revisions=[str(revision_id) for revision_id in revisions],
            description=text,
            proposed_fix=(proposed_fix or "").strip() or None,
            dedupe_key=dedupe_key,
            assignee_id=assignee_id,
            # Проверка заводит сотню находок одной транзакцией: порядок в реестре не случаен.
            created_at=datetime.now(UTC),
        )

        try:
            # Точка сохранения: отказ по отпечатку не должен откатывать пачку вызывающего.
            async with self._session.begin_nested():
                self._session.add(issue)
                await self._session.flush()
        except IntegrityError:
            # Две проверки нашли одно и то же одновременно: ограничение базы пропустило одну.
            if dedupe_key is not None and (known := await self._by_dedupe(dedupe_key)) is not None:
                return known, False
            raise

        self._event(issue, IssueEventKind.CREATED, to_status=IssueStatus.NEW)

        return issue, True

    # ── чтение ──

    async def get(self, issue_id: uuid.UUID) -> Issue:
        issue = await self._session.scalar(self.scoped(Issue).where(Issue.id == issue_id))
        if issue is None:
            raise NotFoundError("Замечание не найдено")

        return issue

    async def page(
        self,
        selected: IssueFilter,
        *,
        sort: IssueSort = IssueSort.PRIORITY,
        descending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> IssuePage:
        statement = self._filtered(selected)
        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))

        column = _SORT_COLUMNS[sort]
        rows = list(
            await self._session.scalars(
                statement.order_by(
                    column.desc() if descending else column.asc(),
                    Issue.id.desc() if descending else Issue.id.asc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )

        return IssuePage(total=int(total or 0), items=await self.rows_of(rows))

    async def everything(self, selected: IssueFilter, *, ceiling: int) -> list[IssueRow]:
        """Весь отбор для выгрузки. Больше потолка не собирается: файл держится в памяти."""
        statement = self._filtered(selected)
        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        if int(total or 0) > ceiling:
            raise ConflictError(
                f"В отборе больше {ceiling} замечаний: сузьте его по книге, главе или состоянию"
            )

        rows = await self._session.scalars(statement.order_by(Issue.code))

        return await self.rows_of(list(rows))

    async def stats(self, selected: IssueFilter) -> IssueStats:
        """Счёт по отбору. Архив не считается: в нём только решённое."""
        statement = self._filtered(selected)
        ours = statement.subquery()
        rows = await self._session.execute(
            select(ours.c.status, ours.c.severity, ours.c.category, func.count()).group_by(
                ours.c.status, ours.c.severity, ours.c.category
            )
        )

        stats = IssueStats()
        for status, severity, category, amount in rows.all():
            count = int(amount)
            stats.total += count
            stats.by_status[status.value] = stats.by_status.get(status.value, 0) + count
            stats.by_severity[severity.value] = stats.by_severity.get(severity.value, 0) + count
            stats.by_category[category.value] = stats.by_category.get(category.value, 0) + count

            if status in OPEN and severity is IssueSeverity.CRITICAL:
                stats.open_critical += count
            if status in OPEN and severity is IssueSeverity.MAJOR:
                stats.open_major += count

        return stats

    async def view(self, issue_id: uuid.UUID) -> IssueView:
        issue = await self.get(issue_id)
        [row] = await self.rows_of([issue])

        chapter = await self._chapter(issue.chapter_id)
        block = await self._block(issue.block_id) if issue.block_id is not None else None
        item = await self._object(issue.object_id) if issue.object_id is not None else None
        own = await self._own_blocks(item) if item is not None else []
        subject = [block] if block is not None else own

        current = await self._current_of(subject)

        return IssueView(
            row=row,
            chapter=chapter,
            current=current,
            block_active=all(entry.active for entry in subject) if subject else False,
            context=await self._neighbours(subject),
            terms=await self._terms(issue, chapter),
            objects=await self._linked_objects(issue, block, item, chapter),
            events=await self._events(issue.id),
            attachments=await self.attachments(issue.id),
            candidates=await self._candidates(issue, subject),
            editable=await self._editable(issue, subject),
            children=await self._children(issue.id),
            parent=(
                await self.get(issue.parent_issue_id) if issue.parent_issue_id is not None else None
            ),
            actions=self.actions_for(issue),
            review_note=await self._review_note(issue),
        )

    def actions_for(self, issue: Issue) -> list[str]:
        """Какие действия доступны этому человеку сейчас.

        Витрина рисует кнопки по этому списку, а не по своей копии таблицы переходов и прав.
        Настоящая проверка всё равно в самом действии: кнопка — подсказка, а не защита.
        """
        role = self._context.role
        deciding = role is Role.OWNER or role in DECIDING_ROLES
        working = deciding or role in REGISTERING_ROLES
        archiving = role is Role.OWNER or role in ARCHIVING_ROLES

        if issue.archived_at is not None:
            return ["restore"] if archiving else []

        status = issue.status
        actions: list[str] = []

        if working:
            actions.append("comment")
        if deciding and can_transition(status, IssueStatus.CONFIRMED):
            actions.append("confirm")
        if deciding and can_transition(status, IssueStatus.REJECTED):
            actions.append("reject")
        if deciding and can_transition(status, IssueStatus.NEEDS_CLARIFICATION):
            actions.append("request_clarification")
        if working and status is IssueStatus.NEEDS_CLARIFICATION:
            actions.append("answer_clarification")
        if working and can_transition(status, IssueStatus.FIXED):
            actions.extend(["edit", "fix"])
        if deciding and can_transition(status, IssueStatus.VERIFIED):
            actions.append("verify")
        if deciding and can_transition(status, IssueStatus.CLOSED):
            actions.append("close")
        if (
            working
            and status is not IssueStatus.NEEDS_CLARIFICATION
            and can_transition(status, IssueStatus.REOPENED)
        ):
            actions.append("reopen")
        if deciding and status not in DECIDED:
            actions.extend(["reclassify", "assign"])
        if archiving and status in DECIDED:
            actions.append("archive")

        return actions

    # ── решения по находке ──

    async def confirm(self, issue_id: uuid.UUID, *, note: str | None = None) -> Issue:
        return await self._decide(issue_id, IssueStatus.CONFIRMED, note)

    async def reject(self, issue_id: uuid.UUID, *, note: str) -> Issue:
        """Отклонить. Перевод это не меняет, запись остаётся в истории и реестре."""
        return await self._decide(issue_id, IssueStatus.REJECTED, _required(note, "отказа"))

    async def request_clarification(self, issue_id: uuid.UUID, *, note: str) -> Issue:
        self._context.require(*DECIDING_ROLES)

        issue = await self._locked(issue_id)
        self._move(issue, IssueStatus.NEEDS_CLARIFICATION, note=_required(note, "вопроса"))

        return await self._saved(issue)

    async def answer_clarification(self, issue_id: uuid.UUID, *, note: str) -> Issue:
        """Ответ на вопрос возвращает замечание на решение, с актуальной редакцией."""
        self._context.require(*REGISTERING_ROLES)

        issue = await self._locked(issue_id)
        if issue.status is not IssueStatus.NEEDS_CLARIFICATION:
            raise ConflictError("Уточнения по этому замечанию никто не просил")

        return await self._reopened(issue, _required(note, "ответа"))

    async def _decide(self, issue_id: uuid.UUID, target: IssueStatus, note: str | None) -> Issue:
        self._context.require(*DECIDING_ROLES)

        issue = await self._locked(issue_id)
        require_transition(issue.status, target)

        await self._require_second_person(issue, issue.detected_by_id, "нашёл")

        issue.reviewed_by_id = self._context.user.id
        self._move(issue, target, note=_clean(note))

        return await self._saved(issue)

    # ── исправление и его проверка ──

    async def edit(
        self,
        issue_id: uuid.UUID,
        *,
        block_id: uuid.UUID,
        base_revision_id: uuid.UUID,
        text: str,
        note: str | None = None,
    ) -> Issue:
        """Исправить текст по подтверждённому замечанию: новая редакция, черновик не трогается.

        Правка называет редакцию, которую человек видел. Если текущая уже другая, это конфликт, а
        не затирание: кто-то успел раньше, и сравнивать надо заново. Замечание переходит в
        «исправлено» и не закрывается само: проверять будет другой шаг.
        """
        self._context.require(*REGISTERING_ROLES)

        issue = await self._locked(issue_id)
        self._require_live(issue)

        # Двое правили одно замечание: второму важно знать именно это, а не про состояния.
        if issue.status is IssueStatus.FIXED:
            raise ConflictError(
                "Замечание уже исправил другой редактор: сравните текст ещё раз. Если исправление "
                "не подходит, откройте замечание заново"
            )

        require_transition(issue.status, IssueStatus.FIXED)

        subject = await self._subject_of(issue)

        if block_id not in {entry.id for entry in subject}:
            raise ConflictError("Этот блок не относится к замечанию")

        block = await self._session.scalar(
            self.scoped(Block).where(Block.id == block_id).with_for_update()
        )
        if block is None:
            raise NotFoundError("Блок не найден")
        if not block.active:
            raise ConflictError("Блок больше не входит в текущую версию мастера")
        if is_protected(block.kind, block.source_text):
            raise ConflictError("Этот блок переносится знак в знак: править в нём нечего")

        if block.current_revision_id != base_revision_id:
            raise ConflictError("Текст уже изменён другим редактором: сравните ещё раз")

        clean = text.strip()
        if not clean:
            raise InvalidInputError("Исправленный текст пуст")
        if "⟦" in clean:
            raise InvalidInputError("В тексте остался заменитель объекта")

        base = await self._session.get(TranslationRevision, base_revision_id)
        if base is None:
            raise NotFoundError("Редакция не найдена")
        if base.text == clean:
            raise InvalidInputError("Текст не изменился")

        number = await self._session.scalar(
            select(func.max(TranslationRevision.revision_no)).where(
                TranslationRevision.block_id == block.id
            )
        )
        revision = TranslationRevision(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            block_id=block.id,
            revision_no=int(number or 0) + 1,
            stage=RevisionStage.WORKING,
            origin=RevisionOrigin.HUMAN,
            text=clean,
            supersedes_id=base.id,
            created_by_id=self._context.user.id,
        )
        self._session.add(revision)
        await self._session.flush()
        block.current_revision_id = revision.id

        await self._mark_fixed(issue, block, revision, old_text=base.text, note=note)

        return await self._saved(issue)

    async def fix(
        self, issue_id: uuid.UUID, *, revision_id: uuid.UUID, note: str | None = None
    ) -> Issue:
        """Связать подтверждённое замечание с редакцией, которая его исправляет.

        Редакция обязана быть текущей у блока этого замечания и новее найденной. Иначе «исправлено»
        указывало бы на текст, которого читатель не увидит, или на тот самый ошибочный.
        """
        self._context.require(*REGISTERING_ROLES)

        issue = await self._locked(issue_id)
        require_transition(issue.status, IssueStatus.FIXED)

        revision = await self._session.scalar(
            self.scoped(TranslationRevision).where(TranslationRevision.id == revision_id)
        )
        if revision is None:
            raise NotFoundError("Редакция не найдена")

        subject = await self._subject_of(issue)
        block = next((entry for entry in subject if entry.id == revision.block_id), None)

        if block is None:
            raise ConflictError("Эта редакция относится к другому блоку")
        if block.current_revision_id != revision.id:
            raise ConflictError("Эта редакция не текущая: читатель её не увидит")
        if str(revision.id) in issue.discovered_revisions:
            raise ConflictError("Замечание поставлено на эту самую редакцию: она его не исправляет")

        base = (
            await self._session.get(TranslationRevision, revision.supersedes_id)
            if revision.supersedes_id is not None
            else None
        )
        await self._mark_fixed(
            issue,
            block,
            revision,
            old_text=base.text if base is not None else (issue.target_snapshot or ""),
            note=note,
        )

        return await self._saved(issue)

    async def _mark_fixed(
        self,
        issue: Issue,
        block: Block,
        revision: TranslationRevision,
        *,
        old_text: str,
        note: str | None,
    ) -> None:
        """Перевести в «исправлено» и завести регрессию: что могло задеть это изменение."""
        issue.fix_revision_id = revision.id
        issue.fixed_by_id = self._context.user.id
        self._move(issue, IssueStatus.FIXED, note=_clean(note), revision_id=revision.id)

        await RegressionGraph(self._session, self._context, self._storage).open_for(
            issue,
            block,
            old_text=old_text,
            new_text=revision.text,
            revision_id=revision.id,
        )

    async def verify(self, issue_id: uuid.UUID, *, note: str | None = None) -> Issue:
        """Подтвердить исправление. Проверяется та редакция, что стоит в тексте сейчас."""
        self._context.require(*DECIDING_ROLES)

        issue = await self._locked(issue_id)
        require_transition(issue.status, IssueStatus.VERIFIED)

        await self._require_second_person(issue, issue.fixed_by_id, "исправил")

        revision = await self._session.get(TranslationRevision, issue.fix_revision_id)
        block = await self._block(revision.block_id) if revision is not None else None

        if block is None or block.current_revision_id != issue.fix_revision_id:
            raise ConflictError(
                "Текст изменился после исправления: проверять надо новую редакцию. "
                "Откройте замечание заново"
            )

        issue.fix_checked_by_id = self._context.user.id
        self._move(
            issue, IssueStatus.VERIFIED, note=_clean(note), revision_id=issue.fix_revision_id
        )

        if await memory_publish_for(self._session, self.organization_id) is MemoryPublish.VERIFIED:
            await self._publish(issue)

        return await self._saved(issue)

    async def close(self, issue_id: uuid.UUID, *, note: str | None = None) -> Issue:
        self._context.require(*DECIDING_ROLES)

        issue = await self._locked(issue_id)
        require_transition(issue.status, IssueStatus.CLOSED)

        unresolved = [
            child.code for child in await self._children(issue.id) if child.status in OPEN
        ]
        if unresolved:
            raise ConflictError("Сначала решите дочерние замечания: " + ", ".join(unresolved))

        pending = await self._regression_pending(issue)
        if pending:
            raise ConflictError(
                f"Сначала завершите регрессию: не решено обязательных мест — {pending}"
            )

        self._move(issue, IssueStatus.CLOSED, note=_clean(note), revision_id=issue.fix_revision_id)

        if await memory_publish_for(self._session, self.organization_id) is MemoryPublish.CLOSED:
            await self._publish(issue)

        return await self._saved(issue)

    async def _regression_pending(self, issue: Issue) -> int:
        """Сколько обязательных мест не решено в прогоне нынешнего исправления."""
        amount = await self._session.scalar(
            select(func.count())
            .select_from(RegressionItem)
            .join(RegressionRun, RegressionRun.id == RegressionItem.run_id)
            .where(
                RegressionRun.issue_id == issue.id,
                RegressionRun.fix_revision_id == issue.fix_revision_id,
                RegressionItem.required.is_(True),
                RegressionItem.decision == RegressionDecision.PENDING,
            )
        )

        return int(amount or 0)

    async def _publish(self, issue: Issue) -> None:
        """Проверенное исправление — в память переводов; раньше проверки оно туда не попадает."""
        revision = await self._session.get(TranslationRevision, issue.fix_revision_id)
        if revision is None:
            return

        block = await self._block(revision.block_id)
        if is_protected(block.kind, block.source_text):
            return

        book = await self._book(issue.book_id)

        await TranslationMemory(self._session, self._context).remember(
            [(block.source_text, revision.text)],
            source_language=book.source_language,
            target_language=book.target_language,
            origin=HUMAN,
            verified=True,
        )

    async def reopen(self, issue_id: uuid.UUID, *, note: str) -> Issue:
        self._context.require(*REGISTERING_ROLES)

        issue = await self._locked(issue_id)
        if issue.status is IssueStatus.NEEDS_CLARIFICATION:
            raise ConflictError("Замечание ждёт уточнения: ответьте на вопрос")

        return await self._reopened(issue, _required(note, "причины"))

    async def _reopened(self, issue: Issue, note: str) -> Issue:
        """Открыть заново: причина и актуальная редакция обязательны, прежнее исправление снято."""
        require_transition(issue.status, IssueStatus.REOPENED)

        current = await self._current_of(await self._subject_of(issue))

        # Прогон был про прежнее исправление: решения по нему к новому тексту не относятся.
        await self._session.execute(
            update(RegressionRun)
            .where(
                RegressionRun.issue_id == issue.id,
                RegressionRun.status != RegressionStatus.COMPLETED,
            )
            .values(status=RegressionStatus.SUPERSEDED)
        )

        issue.fix_revision_id = None
        issue.fixed_by_id = None
        issue.fix_checked_by_id = None
        issue.reviewed_by_id = None
        self._move(
            issue,
            IssueStatus.REOPENED,
            note=note,
            revision_id=current.id if current is not None else None,
        )

        return await self._saved(issue)

    # ── классификация и прочее ──

    async def reclassify(
        self,
        issue_id: uuid.UUID,
        *,
        reason: str,
        category: IssueCategory | None = None,
        severity: IssueSeverity | None = None,
    ) -> Issue:
        """Сменить разряд или серьёзность. Причина обязательна, прежнее остаётся в ленте."""
        self._context.require(*DECIDING_ROLES)

        note = _required(reason, "причины")
        issue = await self._locked(issue_id)
        self._require_live(issue)

        if issue.status in DECIDED:
            raise ConflictError("По замечанию уже принято решение: сначала откройте его заново")

        changes: dict[str, list[str]] = {}
        if category is not None and category is not issue.category:
            changes["category"] = [issue.category.value, category.value]
            issue.category = category
        if severity is not None and severity is not issue.severity:
            changes["severity"] = [issue.severity.value, severity.value]
            issue.severity = severity

        if not changes:
            raise InvalidInputError("Разряд и серьёзность остались прежними")

        item = await self._object(issue.object_id) if issue.object_id is not None else None
        issue.priority_score = priority_of(issue.severity, issue.impact_count, item)
        self._event(issue, IssueEventKind.RECLASSIFIED, note=note, payload=changes)

        return await self._saved(issue)

    async def assign(self, issue_id: uuid.UUID, *, assignee_id: uuid.UUID | None) -> Issue:
        self._context.require(*DECIDING_ROLES)

        issue = await self._locked(issue_id)
        self._require_live(issue)

        if assignee_id is not None:
            await self._require_member(assignee_id)

        issue.assignee_id = assignee_id
        self._event(
            issue,
            IssueEventKind.ASSIGNED,
            payload={"assignee_id": str(assignee_id) if assignee_id is not None else None},
        )

        return await self._saved(issue)

    async def comment(self, issue_id: uuid.UUID, *, note: str) -> Issue:
        self._context.require(*REGISTERING_ROLES)

        issue = await self._locked(issue_id)
        self._require_live(issue)
        self._event(issue, IssueEventKind.COMMENTED, note=_required(note, "комментария"))

        return await self._saved(issue)

    async def archive(self, issue_id: uuid.UUID, *, note: str | None = None) -> Issue:
        """Убрать решённое с глаз. Запись остаётся: архив — это флаг, а не удаление."""
        self._context.require(*ARCHIVING_ROLES)

        issue = await self._locked(issue_id)
        self._require_live(issue)

        if issue.status not in DECIDED:
            raise ConflictError("В архив уходит только решённое замечание")

        issue.archived_at = datetime.now(UTC)
        self._event(issue, IssueEventKind.ARCHIVED, note=_clean(note))

        return await self._saved(issue)

    async def restore(self, issue_id: uuid.UUID) -> Issue:
        self._context.require(*ARCHIVING_ROLES)

        issue = await self._locked(issue_id)
        if issue.archived_at is None:
            raise ConflictError("Замечание не в архиве")

        issue.archived_at = None
        self._event(issue, IssueEventKind.RESTORED)

        return await self._saved(issue)

    # ── вложения ──

    async def attachments(self, issue_id: uuid.UUID) -> list[IssueAttachment]:
        rows = await self._session.scalars(
            self.scoped(IssueAttachment)
            .where(IssueAttachment.issue_id == issue_id)
            .order_by(IssueAttachment.created_at)
        )

        return list(rows)

    async def record_attachment(self, attachment: IssueAttachment) -> IssueAttachment:
        """Записать принятый файл: сам файл к этому моменту уже в хранилище."""
        issue = await self._locked(attachment.issue_id)
        self._session.add(attachment)
        self._event(
            issue,
            IssueEventKind.ATTACHED,
            payload={"filename": attachment.filename, "content_hash": attachment.content_hash},
        )
        await self._session.commit()
        await self._session.refresh(attachment)

        return attachment

    async def attachment(self, issue_id: uuid.UUID, attachment_id: uuid.UUID) -> IssueAttachment:
        found = await self._session.scalar(
            self.scoped(IssueAttachment).where(
                IssueAttachment.id == attachment_id, IssueAttachment.issue_id == issue_id
            )
        )
        if found is None:
            raise NotFoundError("Вложение не найдено")

        return found

    # ── внутреннее ──

    def _filtered(self, selected: IssueFilter) -> Select[tuple[Issue]]:
        statement = self.scoped(Issue)

        statement = (
            statement.where(Issue.archived_at.is_not(None))
            if selected.archived
            else statement.where(Issue.archived_at.is_(None))
        )

        if selected.book_id is not None:
            statement = statement.where(Issue.book_id == selected.book_id)
        if selected.chapter_id is not None:
            statement = statement.where(Issue.chapter_id == selected.chapter_id)
        if selected.block_id is not None:
            statement = statement.where(Issue.block_id == selected.block_id)
        if selected.object_id is not None:
            statement = statement.where(Issue.object_id == selected.object_id)
        if selected.statuses:
            statement = statement.where(Issue.status.in_(selected.statuses))
        if selected.severity is not None:
            statement = statement.where(Issue.severity == selected.severity)
        if selected.category is not None:
            statement = statement.where(Issue.category == selected.category)
        if selected.assignee_id is not None:
            statement = statement.where(Issue.assignee_id == selected.assignee_id)
        if selected.query is not None and selected.query.strip():
            pattern = contains(selected.query)
            statement = statement.where(
                Issue.code.ilike(pattern, escape=ESCAPE)
                | Issue.description.ilike(pattern, escape=ESCAPE)
            )

        return statement

    async def rows_of(self, issues: Sequence[Issue]) -> list[IssueRow]:
        """Подписи для строк одним проходом на вид записи."""
        if not issues:
            return []

        books = await self._by_id(BookEdition, {issue.book_id for issue in issues})
        chapters = await self._by_id(Chapter, {issue.chapter_id for issue in issues})
        blocks = await self._by_id(
            Block, {issue.block_id for issue in issues if issue.block_id is not None}
        )
        objects = await self._by_id(
            BookObject, {issue.object_id for issue in issues if issue.object_id is not None}
        )
        people = {
            person
            for issue in issues
            for person in (issue.detected_by_id, issue.assignee_id)
            if person is not None
        }
        names = await self._names(people)

        def prefixed(chapter_id: uuid.UUID, code: str) -> str:
            prefix = chapters[chapter_id].code
            return f"{prefix}-{code}" if prefix is not None else code

        return [
            IssueRow(
                issue=issue,
                book_title=books[issue.book_id].title,
                block_code=(
                    prefixed(issue.chapter_id, blocks[issue.block_id].code)
                    if issue.block_id is not None
                    else None
                ),
                object_code=(
                    prefixed(issue.chapter_id, objects[issue.object_id].code)
                    if issue.object_id is not None
                    else None
                ),
                detected_by=names.get(issue.detected_by_id) if issue.detected_by_id else None,
                assignee=names.get(issue.assignee_id) if issue.assignee_id else None,
            )
            for issue in issues
        ]

    async def _by_id(self, model: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
        if not ids:
            return {}

        rows = await self._session.scalars(self.scoped(model).where(model.id.in_(ids)))

        return {row.id: row for row in rows}

    async def _names(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
        wanted = set(ids)
        if not wanted:
            return {}

        rows = await self._session.execute(select(User.id, User.email).where(User.id.in_(wanted)))

        return {row[0]: row[1] for row in rows.all()}

    async def _locked(self, issue_id: uuid.UUID) -> Issue:
        issue = await self._session.scalar(
            self.scoped(Issue).where(Issue.id == issue_id).with_for_update()
        )
        if issue is None:
            raise NotFoundError("Замечание не найдено")

        return issue

    def _require_live(self, issue: Issue) -> None:
        if issue.archived_at is not None:
            raise ConflictError("Замечание в архиве: сначала верните его")

    def _move(
        self,
        issue: Issue,
        target: IssueStatus,
        *,
        note: str | None = None,
        revision_id: uuid.UUID | None = None,
    ) -> None:
        """Единственное место, где меняется статус."""
        self._require_live(issue)
        require_transition(issue.status, target)

        previous = issue.status
        issue.status = target
        self._event(
            issue,
            IssueEventKind.STATUS_CHANGED,
            from_status=previous,
            to_status=target,
            note=note,
            revision_id=revision_id,
        )

    def _event(
        self,
        issue: Issue,
        kind: IssueEventKind,
        *,
        from_status: IssueStatus | None = None,
        to_status: IssueStatus | None = None,
        note: str | None = None,
        revision_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            IssueEvent(
                organization_id=self.organization_id,
                issue_id=issue.id,
                kind=kind,
                from_status=from_status,
                to_status=to_status,
                # Нашла проверка: запуск заказал человек, но регистрировал не он.
                actor_id=None
                if issue.automatic and kind is IssueEventKind.CREATED
                else self._context.user.id,
                note=note,
                related_revision_id=revision_id,
                payload=payload or {},
                # Время часов, а не начала транзакции: иначе события одной транзакции получат
                # одну метку, и порядок в ленте станет случайным.
                created_at=datetime.now(UTC),
            )
        )
        AuditService(self._session, self._context).record(
            kind=f"issue.{kind.value}",
            subject_type="issue",
            subject_id=issue.id,
            payload={
                "code": issue.code,
                "from": from_status.value if from_status is not None else None,
                "to": to_status.value if to_status is not None else None,
                "note": note,
                **(payload or {}),
            },
        )

    async def _saved(self, issue: Issue) -> Issue:
        await self._session.commit()
        await self._session.refresh(issue)

        return issue

    async def _require_second_person(
        self, issue: Issue, author_id: uuid.UUID | None, verb: str
    ) -> None:
        if issue.severity is not IssueSeverity.CRITICAL or author_id != self._context.user.id:
            return

        if await self._two_person_review():
            raise ConflictError(
                f"Критичное замечание решает не тот, кто его {verb}: так настроено пространство"
            )

    async def _review_note(self, issue: Issue) -> str | None:
        if issue.severity is not IssueSeverity.CRITICAL:
            return None

        me = self._context.user.id
        mine = (
            issue.status in (IssueStatus.NEW, IssueStatus.REOPENED) and issue.detected_by_id == me
        ) or (issue.status is IssueStatus.FIXED and issue.fixed_by_id == me)

        if mine and await self._two_person_review():
            return "Это критичное замечание — ваше: решение за другим участником."

        return None

    async def _two_person_review(self) -> bool:
        enabled = await self._session.scalar(
            select(WorkspaceSettings.two_person_review).where(
                WorkspaceSettings.organization_id == self.organization_id
            )
        )

        return bool(enabled)

    async def _by_dedupe(self, key: str) -> Issue | None:
        found: Issue | None = await self._session.scalar(
            self.scoped(Issue).where(Issue.dedupe_key == key)
        )

        return found

    async def _block(self, block_id: uuid.UUID) -> Block:
        block = await self._session.scalar(self.scoped(Block).where(Block.id == block_id))
        if block is None:
            raise NotFoundError("Блок не найден")

        return block

    async def _object(self, object_id: uuid.UUID) -> BookObject:
        return await ObjectService(self._session, self._context, self._storage).get(object_id)

    async def _own_blocks(self, item: BookObject) -> list[Block]:
        view = await ObjectService(self._session, self._context, self._storage).view(
            item.id, master_id=None
        )

        return own_blocks(view.placed)

    async def _subject_of(self, issue: Issue) -> list[Block]:
        if issue.block_id is not None:
            return [await self._block(issue.block_id)]

        return await self._own_blocks(await self._object(issue.object_id))  # type: ignore[arg-type]

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))
        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _book(self, book_id: uuid.UUID) -> BookEdition:
        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))
        if book is None:
            raise NotFoundError("Книга не найдена")

        return book

    async def _parent(self, parent_id: uuid.UUID, book_id: uuid.UUID) -> Issue:
        parent = await self.get(parent_id)
        if parent.book_id != book_id:
            raise InvalidInputError("Родительское замечание относится к другой книге")

        return parent

    async def _require_member(self, user_id: uuid.UUID) -> None:
        member = await self._session.scalar(
            select(Membership.user_id).where(
                Membership.organization_id == self.organization_id, Membership.user_id == user_id
            )
        )
        if member is None:
            raise InvalidInputError("Назначить можно только участника этого пространства")

    async def _revisions(
        self, ids: Iterable[uuid.UUID | None]
    ) -> dict[uuid.UUID, TranslationRevision]:
        return await self._by_id(TranslationRevision, {i for i in ids if i is not None})

    async def _current_of(self, subject: Sequence[Block]) -> TranslationRevision | None:
        for block in subject:
            if block.current_revision_id is not None:
                revision: TranslationRevision | None = await self._session.get(
                    TranslationRevision, block.current_revision_id
                )
                return revision

        return None

    async def _impact(self, book_id: uuid.UUID, block: Block) -> int:
        """Сколько действующих блоков книги с тем же исходным текстом."""
        amount = await self._session.scalar(
            select(func.count())
            .select_from(Block)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .where(
                Block.organization_id == self.organization_id,
                Chapter.book_id == book_id,
                Block.active.is_(True),
                Block.source_hash == block.source_hash,
            )
        )

        return max(1, int(amount or 0))

    async def _neighbours(self, subject: Sequence[Block]) -> list[Neighbour]:
        """Соседние блоки: без них проверяющий судит о переводе в отрыве от текста."""
        if not subject:
            return []

        first, last = min(b.ordinal for b in subject), max(b.ordinal for b in subject)
        own = {block.id for block in subject}
        rows = await self._session.execute(
            select(Block, TranslationRevision.text)
            .outerjoin(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(
                Block.organization_id == self.organization_id,
                Block.chapter_id == subject[0].chapter_id,
                Block.active.is_(True),
                Block.ordinal.between(first - CONTEXT_BLOCKS, last + CONTEXT_BLOCKS),
            )
            .order_by(Block.ordinal)
        )

        return [
            Neighbour(block=block, translation=text)
            for block, text in rows.all()
            if block.id not in own
        ]

    async def _terms(self, issue: Issue, chapter: Chapter) -> list[Term]:
        """Термины действующей версии глоссария, встречающиеся в этом тексте."""
        version = await TerminologyGate(self._session, self._context).effective(
            chapter.book_id, chapter.id
        )
        if version is None:
            return []

        glossary = await GlossaryService(self._session, self._context).load_version(version.id)

        return list(glossary.match(issue.source_snapshot))

    async def _linked_objects(
        self, issue: Issue, block: Block | None, item: BookObject | None, chapter: Chapter
    ) -> list[LinkedObject]:
        found: dict[uuid.UUID, BookObject] = {}
        if item is not None:
            found[item.id] = item

        if block is not None:
            rows = await self._session.scalars(
                self.scoped(BookObject)
                .join(ObjectReference, ObjectReference.object_id == BookObject.id)
                .where(ObjectReference.block_id == block.id)
            )
            found.update({row.id: row for row in rows})

        return [LinkedObject(object=entry, chapter_code=chapter.code) for entry in found.values()]

    async def _events(self, issue_id: uuid.UUID) -> list[EventRow]:
        events = list(
            await self._session.scalars(
                self.scoped(IssueEvent)
                .where(IssueEvent.issue_id == issue_id)
                .order_by(IssueEvent.created_at, IssueEvent.id)
            )
        )
        names = await self._names(event.actor_id for event in events if event.actor_id is not None)

        return [
            EventRow(event=event, actor=names.get(event.actor_id) if event.actor_id else None)
            for event in events
        ]

    async def _candidates(self, issue: Issue, subject: Sequence[Block]) -> list[FixCandidate]:
        if not can_transition(issue.status, IssueStatus.FIXED):
            return []

        revisions = await self._revisions(block.current_revision_id for block in subject)

        return [
            FixCandidate(revision=revisions[block.current_revision_id], block=block)
            for block in subject
            if block.current_revision_id is not None
            and str(block.current_revision_id) not in issue.discovered_revisions
        ]

    async def _editable(self, issue: Issue, subject: Sequence[Block]) -> list[FixCandidate]:
        if not can_transition(issue.status, IssueStatus.FIXED):
            return []

        revisions = await self._revisions(block.current_revision_id for block in subject)

        return [
            FixCandidate(revision=revisions[block.current_revision_id], block=block)
            for block in subject
            if block.current_revision_id is not None
            and block.active
            and not is_protected(block.kind, block.source_text)
        ]

    async def _children(self, issue_id: uuid.UUID) -> list[Issue]:
        rows = await self._session.scalars(
            self.scoped(Issue).where(Issue.parent_issue_id == issue_id).order_by(Issue.code)
        )

        return list(rows)


def priority_of(severity: IssueSeverity, impact: int, item: BookObject | None) -> int:
    """Вес для сортировки: серьёзность, сколько мест затронуто, чем рискует объект."""
    risk = OBJECT_RISK.get(item.type, 0) if item is not None else 0

    return SEVERITY_WEIGHT[severity] + min(impact, IMPACT_CEILING) + risk


def _source_of(item: BookObject | None, subject: Sequence[Block]) -> str:
    """Исходный текст на момент находки. У формулы без блоков текст лежит в самом объекте."""
    if subject:
        return "\n".join(block.source_text for block in subject)

    payload = item.payload if item is not None else {}

    return str(payload.get("text") or payload.get("raw") or "")


def _target_of(
    subject: Sequence[Block], revisions: dict[uuid.UUID, TranslationRevision]
) -> str | None:
    texts = [
        revisions[block.current_revision_id].text
        for block in subject
        if block.current_revision_id is not None
    ]

    return "\n".join(texts) if texts else None


def _clean(note: str | None) -> str | None:
    return (note or "").strip() or None


def _required(note: str | None, what: str) -> str:
    text = _clean(note)
    if text is None:
        raise InvalidInputError(f"Напишите текст {what}: без него решение ничем не объяснено")

    return text
