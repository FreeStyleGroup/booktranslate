"""Сводка по рабочему пространству.

Кабинет открывают чаще всего, и открывают его ради ответа на три вопроса:
что сейчас в работе, где меня ждут и во сколько это обошлось. Собирать эти
ответы десятком запросов со стороны витрины нельзя — получится кабинет,
который открывается три секунды и на медленной связи не открывается вовсе.

Поэтому сводка считается на стороне API одним обращением. Запросы внутри
намеренно сгруппированные: «сколько документов в каком состоянии» — это
один запрос с GROUP BY, а не по запросу на документ.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.models.catalog import CatalogEntry
from app.models.document import Document, DocumentStatus
from app.models.memory import GlossaryTerm, TranslationUnit
from app.models.project import Project
from app.models.segment import Segment, SegmentStatus
from app.models.terminology import TermCandidate, TermCandidateStatus
from app.services.base import TenantModel, TenantService
from app.services.providers.base import Usage

# Сколько строк показывать в списках сводки. Кабинет — не отчёт: пять
# документов и пять замечаний отвечают на «за что взяться», а двести строк
# на главной не читает никто.
RECENT = 5


@dataclass(slots=True)
class DocumentCard:
    id: uuid.UUID
    title: str
    status: DocumentStatus
    segments: int
    done: int

    @property
    def ready_percent(self) -> int:
        """Готовность в процентах — то, что человек ищет глазами первым."""
        if self.segments == 0:
            return 0

        return round(self.done * 100 / self.segments)


@dataclass(slots=True)
class FindingCard:
    segment_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    position: int
    source_text: str
    target_text: str | None
    checks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Overview:
    projects: int = 0
    documents: int = 0
    segments: int = 0

    documents_by_status: dict[str, int] = field(default_factory=dict)
    segments_by_status: dict[str, int] = field(default_factory=dict)

    # Сколько сегментов ждёт человека и сколько терминов не решено. Первое —
    # очередь работы, второе — то, что эту работу останавливает.
    flagged: int = 0
    undecided_terms: int = 0

    glossary_terms: int = 0
    catalog_entries: int = 0
    memory_units: int = 0

    usage: Usage = field(default_factory=Usage)
    # Чем переводили. Нужно, чтобы посчитать деньги: прейскурант у каждой
    # модели свой.
    translated_by: str | None = None

    recent_documents: list[DocumentCard] = field(default_factory=list)
    recent_findings: list[FindingCard] = field(default_factory=list)


class OverviewService(TenantService):
    async def build(self) -> Overview:
        overview = Overview()

        overview.projects = await self._count(Project)
        overview.glossary_terms = await self._count(GlossaryTerm)
        overview.catalog_entries = await self._count(CatalogEntry)
        overview.memory_units = await self._count(TranslationUnit)

        overview.documents_by_status = await self._by_status(Document, Document.status)
        overview.documents = sum(overview.documents_by_status.values())

        overview.segments_by_status = await self._by_status(Segment, Segment.status)
        overview.segments = sum(overview.segments_by_status.values())
        overview.flagged = overview.segments_by_status.get(SegmentStatus.FLAGGED.value, 0)

        overview.undecided_terms = await self._count(
            TermCandidate, TermCandidate.status == TermCandidateStatus.NEW
        )

        overview.usage, overview.translated_by = await self._usage()
        overview.recent_documents = await self._documents()
        overview.recent_findings = await self._findings()

        return overview

    async def _count(self, model: type[TenantModel], *conditions: ColumnElement[bool]) -> int:
        statement = (
            select(func.count())
            .select_from(model)
            .where(model.organization_id == self.organization_id, *conditions)
        )

        return await self._session.scalar(statement) or 0

    async def _by_status(
        self, model: type[TenantModel], column: InstrumentedAttribute[Any]
    ) -> dict[str, int]:
        """Сколько записей в каждом состоянии — одним запросом.

        Ключи — значения перечисления строками: наружу уходит `.value`,
        по которому витрина и рисует подписи.
        """
        rows = await self._session.execute(
            select(column, func.count())
            .select_from(model)
            .where(model.organization_id == self.organization_id)
            .group_by(column)
        )

        return {status.value: amount for status, amount in rows.all()}

    async def _usage(self) -> tuple[Usage, str | None]:
        """Расход по всем документам организации.

        Складывается в базе, а не в приложении: тянуть на витрину тысячу
        документов ради четырёх сумм — это тот случай, когда запрос
        дешевле цикла.
        """
        row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(Document.input_tokens), 0),
                    func.coalesce(func.sum(Document.output_tokens), 0),
                    func.coalesce(func.sum(Document.cached_input_tokens), 0),
                    func.coalesce(func.sum(Document.cache_write_tokens), 0),
                    func.max(Document.translated_by),
                ).where(Document.organization_id == self.organization_id)
            )
        ).one()

        # 🔥 int(): сумму по bigint Postgres возвращает типом numeric, и в
        # Python она приходит Decimal. Пока расход нулевой, coalesce отдаёт
        # обычный ноль и всё сходится; первая переведённая книга приносит
        # Decimal, а прейскурант умножает его на float — и сводка падает.
        usage = Usage(
            input_tokens=int(row[0]),
            output_tokens=int(row[1]),
            cached_input_tokens=int(row[2]),
            cache_write_tokens=int(row[3]),
        )

        return usage, row[4]

    async def _documents(self) -> list[DocumentCard]:
        """Последние документы с готовностью.

        Готовность — доля принятых человеком сегментов, а не переведённых:
        перевод, который никто не смотрел, готовым не является.
        """
        documents = list(
            await self._session.scalars(
                self.scoped(Document).order_by(Document.updated_at.desc()).limit(RECENT)
            )
        )

        if not documents:
            return []

        ids = [document.id for document in documents]

        rows = await self._session.execute(
            select(
                Segment.document_id,
                func.count(),
                func.count().filter(Segment.status == SegmentStatus.APPROVED),
            )
            .where(Segment.document_id.in_(ids))
            .group_by(Segment.document_id)
        )

        counts = {row[0]: (row[1], row[2]) for row in rows.all()}

        return [
            DocumentCard(
                id=document.id,
                title=document.title,
                status=document.status,
                segments=counts.get(document.id, (0, 0))[0],
                done=counts.get(document.id, (0, 0))[1],
            )
            for document in documents
        ]

    async def _findings(self) -> list[FindingCard]:
        """Худшие сегменты с замечаниями — очередь работы редактора."""
        rows = await self._session.execute(
            select(Segment, Document.title)
            .join(Document, Document.id == Segment.document_id)
            .where(
                Segment.organization_id == self.organization_id,
                Segment.status == SegmentStatus.FLAGGED,
            )
            .order_by(Segment.quality_score.desc().nulls_last(), Segment.position)
            .limit(RECENT)
        )

        cards = []

        for segment, title in rows.all():
            findings = (segment.quality or {}).get("findings", [])
            cards.append(
                FindingCard(
                    segment_id=segment.id,
                    document_id=segment.document_id,
                    document_title=title,
                    position=segment.position,
                    source_text=segment.source_text,
                    target_text=segment.target_text,
                    checks=[str(item.get("check", "")) for item in findings],
                )
            )

        return cards
