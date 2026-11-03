"""Сводка по рабочему пространству.

Кабинет открывают чаще всего, и открывают его ради ответа на три вопроса: что сейчас
в работе, где меня ждут и во сколько это обошлось. Собирать эти ответы десятком
запросов со стороны витрины нельзя — получится кабинет, который открывается три
секунды и на медленной связи не открывается вовсе.

Поэтому сводка считается на стороне API одним обращением. Запросы внутри намеренно
сгруппированные: «сколько блоков переведено» — это один запрос, а не по запросу на
главу.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, func, select

from app.models.block import Block
from app.models.book import BookEdition
from app.models.catalog import CatalogEntry
from app.models.chapter import Chapter
from app.models.document import Document
from app.models.job import LIVE, JobState, TranslationJob
from app.models.memory import GlossaryTerm, TranslationUnit
from app.models.project import Project
from app.models.terminology import TermCandidate, TermCandidateStatus
from app.models.translation import TranslationRevision, TranslationRun
from app.services.base import TenantModel, TenantService
from app.services.pricing import estimate_usd
from app.services.providers.base import Usage

# Сколько строк показывать в списках сводки. Кабинет — не отчёт: пять книг и пять
# глав, которые ждут человека, отвечают на «за что взяться», а двести строк на главной
# не читает никто.
RECENT = 5


@dataclass(slots=True)
class BookCard:
    id: uuid.UUID
    code: str
    title: str
    blocks: int
    translated: int

    @property
    def ready_percent(self) -> int:
        """Готовность в процентах — то, что человек ищет глазами первым."""
        if self.blocks == 0:
            return 0

        return round(self.translated * 100 / self.blocks)


@dataclass(slots=True)
class AttentionCard:
    """Прогон, которому нужен человек: сорвался или оставил блоки без перевода."""

    run_id: uuid.UUID
    book_id: uuid.UUID
    chapter_id: uuid.UUID
    title: str
    problem: str


@dataclass(slots=True)
class Overview:
    projects: int = 0
    books: int = 0
    documents: int = 0

    blocks: int = 0
    translated: int = 0
    # Откуда текущие редакции: модель, готовый перевод, защищённое.
    by_origin: dict[str, int] = field(default_factory=dict)

    # Что идёт прямо сейчас и что останавливает работу.
    live_runs: int = 0
    undecided_terms: int = 0

    glossary_terms: int = 0
    catalog_entries: int = 0
    memory_units: int = 0

    usage: Usage = field(default_factory=Usage)
    # Оценка в долларах: прейскурант у каждой модели свой, поэтому складывается
    # по моделям. Пусто — ни одна из моделей не в прейскуранте.
    estimated_usd: float | None = None

    recent_books: list[BookCard] = field(default_factory=list)
    attention: list[AttentionCard] = field(default_factory=list)


class OverviewService(TenantService):
    async def build(self) -> Overview:
        overview = Overview()

        overview.projects = await self._count(Project)
        overview.books = await self._count(BookEdition)
        overview.documents = await self._count(Document)
        overview.glossary_terms = await self._count(GlossaryTerm)
        overview.catalog_entries = await self._count(CatalogEntry)
        overview.memory_units = await self._count(TranslationUnit)
        overview.undecided_terms = await self._count(
            TermCandidate, TermCandidate.status == TermCandidateStatus.NEW
        )
        overview.live_runs = await self._count(TranslationJob, TranslationJob.state.in_(LIVE))

        overview.blocks, overview.translated = await self._progress()
        overview.by_origin = await self._by_origin()
        overview.usage, overview.estimated_usd = await self._usage()
        overview.recent_books = await self._books()
        overview.attention = await self._attention()

        return overview

    async def _count(self, model: type[TenantModel], *conditions: ColumnElement[bool]) -> int:
        statement = (
            select(func.count())
            .select_from(model)
            .where(model.organization_id == self.organization_id, *conditions)
        )

        return await self._session.scalar(statement) or 0

    async def _progress(self) -> tuple[int, int]:
        row = (
            await self._session.execute(
                select(func.count(), func.count(Block.current_revision_id)).where(
                    Block.organization_id == self.organization_id, Block.active.is_(True)
                )
            )
        ).one()

        return int(row[0]), int(row[1])

    async def _by_origin(self) -> dict[str, int]:
        rows = await self._session.execute(
            select(TranslationRevision.origin, func.count())
            .join(Block, Block.current_revision_id == TranslationRevision.id)
            .where(Block.organization_id == self.organization_id, Block.active.is_(True))
            .group_by(TranslationRevision.origin)
        )

        return {origin.value: int(amount) for origin, amount in rows.all()}

    async def _usage(self) -> tuple[Usage, float | None]:
        """Расход по всем прогонам: по моделям, потому что цена у каждой своя."""
        rows = await self._session.execute(
            select(
                TranslationRun.model,
                func.coalesce(func.sum(TranslationRun.input_tokens), 0),
                func.coalesce(func.sum(TranslationRun.output_tokens), 0),
                func.coalesce(func.sum(TranslationRun.cached_input_tokens), 0),
                func.coalesce(func.sum(TranslationRun.cache_write_tokens), 0),
            )
            .where(TranslationRun.organization_id == self.organization_id)
            .group_by(TranslationRun.model)
        )

        usage = Usage()
        total: float | None = None

        for model, spent_in, spent_out, cached, written in rows.all():
            # 🔥 int(): сумму по целым Postgres возвращает типом numeric, и в Python
            # она приходит Decimal, а прейскурант умножает её на float.
            part = Usage(
                input_tokens=int(spent_in),
                output_tokens=int(spent_out),
                cached_input_tokens=int(cached),
                cache_write_tokens=int(written),
            )
            usage = usage + part
            usd = estimate_usd(
                model,
                input_tokens=part.input_tokens,
                output_tokens=part.output_tokens,
                cached_input_tokens=part.cached_input_tokens,
                cache_write_tokens=part.cache_write_tokens,
            )

            if usd is not None:
                total = (total or 0.0) + usd

        return usage, total

    async def _books(self) -> list[BookCard]:
        """Последние книги с готовностью: сколько блоков уже имеют перевод."""
        books = list(
            await self._session.scalars(
                self.scoped(BookEdition).order_by(BookEdition.updated_at.desc()).limit(RECENT)
            )
        )

        if not books:
            return []

        rows = await self._session.execute(
            select(Chapter.book_id, func.count(), func.count(Block.current_revision_id))
            .join(Block, Block.chapter_id == Chapter.id)
            .where(Chapter.book_id.in_([book.id for book in books]), Block.active.is_(True))
            .group_by(Chapter.book_id)
        )
        counts = {row[0]: (int(row[1]), int(row[2])) for row in rows.all()}

        return [
            BookCard(
                id=book.id,
                code=book.code,
                title=book.title,
                blocks=counts.get(book.id, (0, 0))[0],
                translated=counts.get(book.id, (0, 0))[1],
            )
            for book in books
        ]

    async def _attention(self) -> list[AttentionCard]:
        """Последние сорвавшиеся прогоны и прогоны с блоками без перевода."""
        rows = await self._session.execute(
            select(TranslationRun, TranslationJob)
            .join(TranslationJob, TranslationJob.run_id == TranslationRun.id)
            .where(
                TranslationRun.organization_id == self.organization_id,
                (TranslationJob.state == JobState.FAILED)
                | (
                    (TranslationJob.state == JobState.DONE)
                    & (func.jsonb_array_length(TranslationRun.rejections) > 0)
                ),
            )
            .order_by(TranslationRun.created_at.desc())
            .limit(RECENT)
        )

        return [
            AttentionCard(
                run_id=run.id,
                book_id=run.book_id,
                chapter_id=run.chapter_id,
                title=job.title,
                problem=(
                    job.error or "Прогон сорвался"
                    if job.state is JobState.FAILED
                    else f"Без перевода осталось блоков: {len(run.rejections)}"
                ),
            )
            for run, job in rows.all()
        ]
