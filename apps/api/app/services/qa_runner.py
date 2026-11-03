"""Выполнение прогона проверки: пачками, с записью после каждой.

Прогон идёт по блокам главы по порядку и помнит, докуда дошёл: убитый рабочий теряет только
незаконченную пачку, а смысловая сверка не платит второй раз за проверенное.

Находка становится замечанием через реестр, с отпечатком. Повторный прогон той же редакции находит
то же самое и получает ту же запись: дублей нет, а отклонённое человеком не возвращается. Новая
редакция — уже другой текст, и находка на ней получает свой код.

Отсутствие находок ничего не решает: блок получает отметку о проверке, но в финальный текст от
этого не переходит.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.block import Block, BlockKind
from app.models.book import BookEdition
from app.models.chapter import Chapter
from app.models.issue import IssueCategory, IssueSeverity
from app.models.qa import FindingDisposition, QAFinding, QAKind, QARun, QAScope, RevisionCheck
from app.models.translation import TranslationRevision
from app.services.base import TenantService
from app.services.checks import Finding, run_checks
from app.services.context import RequestContext
from app.services.errors import NotFoundError
from app.services.glossary import Glossary, GlossaryService
from app.services.issue_numbers import dedupe_key
from app.services.issues import IssueService
from app.services.protection import stored_spans
from app.services.providers.base import Neighbourhood, ProviderError, Usage
from app.services.providers.semantic import (
    SemanticFinding,
    SemanticRequest,
    SemanticReviewer,
)
from app.services.storage import ObjectStorage
from app.services.terminology_gate import TerminologyGate
from app.services.translation_runner import Advance, first_uses

CONTEXT_BLOCKS = 2
CHECK_SEMANTIC = "semantic"

_RISKY_KINDS = frozenset({BlockKind.TABLE_CELL, BlockKind.CAPTION, BlockKind.WARNING})


class QARunner(TenantService):
    def __init__(
        self,
        session: AsyncSession,
        context: RequestContext,
        storage: ObjectStorage,
        reviewer: SemanticReviewer | None = None,
    ) -> None:
        super().__init__(session, context)
        self._issues = IssueService(session, context, storage)
        self._reviewer = reviewer

    async def advance(self, run_id: uuid.UUID, *, limit: int) -> Advance:
        run = await self._session.scalar(self.scoped(QARun).where(QARun.id == run_id))
        if run is None:
            raise NotFoundError("Прогон проверки не найден")

        order = await self._active_blocks(run.chapter_id)
        rest = [
            block
            for block in order
            if block.ordinal > run.cursor and block.current_revision_id is not None
        ]
        batch = rest[:limit]

        if not batch:
            return Advance(processed=0, remaining=0)

        glossary = await self._glossary(run)
        revisions = await self._revisions(batch)

        if run.kind is QAKind.DETERMINISTIC:
            await self._deterministic(run, order, batch, revisions, glossary)
        else:
            await self._semantic(run, order, batch, revisions, glossary)

        run.cursor = batch[-1].ordinal
        run.blocks_checked += len(batch)
        await self._session.commit()

        return Advance(processed=len(batch), remaining=len(rest) - len(batch))

    # ── правила ──

    async def _deterministic(
        self,
        run: QARun,
        order: Sequence[Block],
        batch: Sequence[Block],
        revisions: dict[uuid.UUID, TranslationRevision],
        glossary: Glossary,
    ) -> None:
        ruled = first_uses(glossary, order)
        terms = {term.source: term for term in glossary.terms}

        for block in batch:
            revision = revisions[block.current_revision_id]  # type: ignore[index]
            findings = run_checks(
                block.source_text,
                revision.text,
                glossary=glossary,
                kind=block.kind,
                protected=_protected_of(block),
                first_use=[terms[name] for name in ruled.get(block.id, ())],
            )

            for finding in findings:
                await self._record(run, block, revision, finding)

            await self._cover(run, revision)

    async def _record(
        self, run: QARun, block: Block, revision: TranslationRevision, finding: Finding
    ) -> None:
        """Каждая находка чем-то кончается: замечанием или названным правилом."""
        run.findings_total += 1

        if finding.not_required is not None:
            self._session.add(
                QAFinding(
                    organization_id=self.organization_id,
                    qa_run_id=run.id,
                    chapter_id=run.chapter_id,
                    block_id=block.id,
                    revision_id=revision.id,
                    kind=run.kind,
                    check_name=finding.check,
                    message=finding.message,
                    category=finding.category,
                    severity=finding.severity,
                    disposition=FindingDisposition.NOT_REQUIRED,
                    rule=finding.not_required,
                )
            )
            return

        await self._registered(
            run,
            block,
            revision,
            check=finding.check,
            message=finding.message,
            category=finding.category,
            severity=finding.severity,
        )

    async def _registered(
        self,
        run: QARun,
        block: Block,
        revision: TranslationRevision,
        *,
        check: str,
        message: str,
        category: IssueCategory,
        severity: IssueSeverity,
        proposed_fix: str | None = None,
    ) -> None:
        issue, created = await self._issues.file(
            block_id=block.id,
            object_id=None,
            category=category,
            severity=severity,
            description=message,
            proposed_fix=proposed_fix,
            dedupe_key=dedupe_key(
                check,
                block_id=block.id,
                object_id=None,
                revision_id=revision.id,
                finding=message,
            ),
            automatic=True,
            qa_run_id=run.id,
        )

        if created:
            run.issues_created += 1

        self._session.add(
            QAFinding(
                organization_id=self.organization_id,
                qa_run_id=run.id,
                chapter_id=run.chapter_id,
                block_id=block.id,
                revision_id=revision.id,
                kind=run.kind,
                check_name=check,
                message=message,
                category=category,
                severity=severity,
                disposition=FindingDisposition.REGISTERED,
                issue_id=issue.id,
            )
        )

    async def _cover(self, run: QARun, revision: TranslationRevision) -> None:
        await self._session.execute(
            insert(RevisionCheck)
            .values(
                id=uuid.uuid4(),
                organization_id=self.organization_id,
                revision_id=revision.id,
                qa_run_id=run.id,
                kind=run.kind,
                check_profile_version=run.check_profile_version,
            )
            .on_conflict_do_nothing(constraint="revision_check_once")
        )

    # ── смысл ──

    async def _semantic(
        self,
        run: QARun,
        order: Sequence[Block],
        batch: Sequence[Block],
        revisions: dict[uuid.UUID, TranslationRevision],
        glossary: Glossary,
    ) -> None:
        if self._reviewer is None:
            raise NotFoundError("Смысловая сверка не подключена")

        reviewed = await self._already_reviewed(list(revisions))
        book = await self._session.get(BookEdition, run.book_id)
        neighbours = _neighbours(order)
        prefix = await self._prefix(run)

        chosen = [
            block
            for block in batch
            if block.current_revision_id not in reviewed
            and block.kind is not BlockKind.CODE
            and (run.scope is QAScope.ALL or _is_risky(block, glossary))
        ]

        if not chosen:
            return

        requests = [
            SemanticRequest(
                key=f"{prefix}{block.code}",
                source_text=block.source_text,
                target_text=revisions[block.current_revision_id].text,  # type: ignore[index]
                source_language=book.source_language,  # type: ignore[union-attr]
                target_language=book.target_language,  # type: ignore[union-attr]
                kind=block.kind.value,
                terms=list(glossary.match(block.source_text)),
                context=neighbours[block.id],
            )
            for block in chosen
        ]

        try:
            answer = await self._reviewer.review(requests)
        except ProviderError as error:
            # Отказ — про эти блоки, а не про прогон: без отметки и с причиной. Сбой сети сюда не
            # попадает и повторяется очередью.
            self._spend(run, error.spent)
            run.rejections = [
                *run.rejections,
                *(
                    {"block_id": str(block.id), "code": block.code, "reason": str(error)}
                    for block in chosen
                ),
            ]
            return

        self._spend(run, answer.usage)

        for block, request in zip(chosen, requests, strict=True):
            revision = revisions[block.current_revision_id]  # type: ignore[index]

            for finding in answer.items[request.key]:
                await self._semantic_finding(run, block, revision, finding)

            await self._cover(run, revision)

    async def _semantic_finding(
        self, run: QARun, block: Block, revision: TranslationRevision, finding: SemanticFinding
    ) -> None:
        run.findings_total += 1

        await self._registered(
            run,
            block,
            revision,
            check=CHECK_SEMANTIC,
            message=finding.description,
            category=finding.category,
            severity=finding.severity,
            proposed_fix=finding.proposed_fix,
        )

    def _spend(self, run: QARun, usage: Usage) -> None:
        run.input_tokens += usage.input_tokens
        run.output_tokens += usage.output_tokens
        run.cached_input_tokens += usage.cached_input_tokens
        run.cache_write_tokens += usage.cache_write_tokens

    async def _already_reviewed(self, revision_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Какие редакции смысловая сверка уже видела: за них второй раз не платят."""
        rows = await self._session.scalars(
            select(RevisionCheck.revision_id).where(
                RevisionCheck.organization_id == self.organization_id,
                RevisionCheck.kind == QAKind.SEMANTIC,
                RevisionCheck.revision_id.in_(revision_ids),
            )
        )

        return set(rows)

    # ── общее ──

    async def _active_blocks(self, chapter_id: uuid.UUID) -> list[Block]:
        rows = await self._session.scalars(
            self.scoped(Block)
            .where(Block.chapter_id == chapter_id, Block.active.is_(True))
            .order_by(Block.ordinal)
        )

        return list(rows)

    async def _revisions(self, blocks: Sequence[Block]) -> dict[uuid.UUID, TranslationRevision]:
        rows = await self._session.scalars(
            self.scoped(TranslationRevision).where(
                TranslationRevision.id.in_([block.current_revision_id for block in blocks])
            )
        )

        return {row.id: row for row in rows}

    async def _glossary(self, run: QARun) -> Glossary:
        version = await TerminologyGate(self._session, self._context).effective(
            run.book_id, run.chapter_id
        )
        if version is None:
            return Glossary([])

        return await GlossaryService(self._session, self._context).load_version(version.id)

    async def _prefix(self, run: QARun) -> str:
        chapter = await self._session.get(Chapter, run.chapter_id)

        return f"{chapter.code}-" if chapter is not None and chapter.code is not None else ""


def _protected_of(block: Block) -> list[str]:
    return [
        block.source_text[span.start : span.end] for span in stored_spans(block.source_location)
    ]


def _is_risky(block: Block, glossary: Glossary) -> bool:
    """Где ошибка смысла дороже всего: читатель перенесёт это в работу, не перепроверяя."""
    if block.kind in _RISKY_KINDS:
        return True

    if any(char.isdigit() for char in block.source_text):
        return True

    if stored_spans(block.source_location):
        return True

    return any(term.mandatory for term in glossary.match(block.source_text))


def _neighbours(order: Sequence[Block]) -> dict[uuid.UUID, Neighbourhood]:
    context: dict[uuid.UUID, Neighbourhood] = {}
    heading: str | None = None

    for index, block in enumerate(order):
        context[block.id] = Neighbourhood(
            before=tuple(
                item.source_text for item in order[max(0, index - CONTEXT_BLOCKS) : index]
            ),
            after=tuple(item.source_text for item in order[index + 1 : index + 1 + CONTEXT_BLOCKS]),
            heading=heading,
        )

        if block.kind is BlockKind.HEADING:
            heading = block.source_text

    return context
