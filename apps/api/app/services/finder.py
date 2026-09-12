"""Общий поиск по кабинету: книги, словарь, каталог справок, сегменты.

Один запрос — четыре ответа. Человек, набравший «клапан» в шапке, не знает
заранее, где это слово лежит: в названии книги, в словаре, в справке или
в тексте на странице сорок. Спрашивать его об этом до поиска значит не
найти вовсе; вместо этого ищется везде, а группы показываются по очереди.

Поиск по подстроке, без морфологии и без полнотекстового индекса: на
объёмах бюро — тысячи терминов, десятки тысяч сегментов — `ILIKE` по
индексированной организации отвечает за доли секунды, а полнотекстовый
поиск с русской морфологией — отдельная работа, которую стоит делать,
когда подстрока перестанет находить.

Из каждой группы берётся немного, а общее число считается отдельно: по
нему видно, что «ещё сорок сегментов» есть, и куда за ними идти.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, or_, select

from app.models.catalog import CatalogEntry
from app.models.document import Document
from app.models.memory import GlossaryTerm
from app.models.segment import Segment
from app.services.base import TenantService
from app.services.search import ESCAPE, contains

# Короче двух знаков — это не поиск, а перебор всей базы по одной букве.
MIN_QUERY = 2


@dataclass(slots=True)
class SegmentHit:
    """Сегмент вместе с книгой: без названия книги строка ни о чём."""

    segment: Segment
    document_title: str


@dataclass(slots=True)
class Group[T]:
    total: int
    items: list[T] = field(default_factory=list)


@dataclass(slots=True)
class Found:
    documents: Group[Document]
    terms: Group[GlossaryTerm]
    entries: Group[CatalogEntry]
    segments: Group[SegmentHit]


class Finder(TenantService):
    async def find(self, query: str, *, per_group: int = 5) -> Found:
        pattern = contains(query)

        return Found(
            documents=await self._documents(pattern, per_group),
            terms=await self._terms(pattern, per_group),
            entries=await self._entries(pattern, per_group),
            segments=await self._segments(pattern, per_group),
        )

    async def _documents(self, pattern: str, limit: int) -> Group[Document]:
        statement = self.scoped(Document).where(
            or_(
                Document.title.ilike(pattern, escape=ESCAPE),
                Document.original_filename.ilike(pattern, escape=ESCAPE),
            )
        )

        return Group(
            total=await self._count(statement),
            items=list(
                await self._session.scalars(
                    statement.order_by(Document.updated_at.desc()).limit(limit)
                )
            ),
        )

    async def _terms(self, pattern: str, limit: int) -> Group[GlossaryTerm]:
        statement = self.scoped(GlossaryTerm).where(
            or_(
                GlossaryTerm.source_term_normalized.ilike(pattern, escape=ESCAPE),
                GlossaryTerm.target_term.ilike(pattern, escape=ESCAPE),
            )
        )

        return Group(
            total=await self._count(statement),
            items=list(
                await self._session.scalars(
                    statement.order_by(GlossaryTerm.source_term_normalized).limit(limit)
                )
            ),
        )

    async def _entries(self, pattern: str, limit: int) -> Group[CatalogEntry]:
        statement = self.scoped(CatalogEntry).where(
            or_(
                CatalogEntry.source_term_normalized.ilike(pattern, escape=ESCAPE),
                CatalogEntry.suggested_target.ilike(pattern, escape=ESCAPE),
                CatalogEntry.definition.ilike(pattern, escape=ESCAPE),
            )
        )

        return Group(
            total=await self._count(statement),
            items=list(
                await self._session.scalars(
                    statement.order_by(CatalogEntry.source_term_normalized).limit(limit)
                )
            ),
        )

    async def _segments(self, pattern: str, limit: int) -> Group[SegmentHit]:
        """Сегменты — с названием книги одним соединением.

        Свежие книги первыми, внутри книги — по порядку: человек, ищущий
        фразу, чаще всего ищет её в том, над чем работает сейчас.
        """
        condition = (
            Segment.organization_id == self.organization_id,
            or_(
                Segment.source_text.ilike(pattern, escape=ESCAPE),
                Segment.target_text.ilike(pattern, escape=ESCAPE),
            ),
        )

        counted = await self._session.scalar(
            select(func.count()).select_from(Segment).where(*condition)
        )

        rows = await self._session.execute(
            select(Segment, Document.title)
            .join(Document, Document.id == Segment.document_id)
            .where(*condition)
            .order_by(Document.updated_at.desc(), Segment.position)
            .limit(limit)
        )

        return Group(
            total=int(counted or 0),
            items=[SegmentHit(segment=segment, document_title=title) for segment, title in rows],
        )

    async def _count(self, statement: Select[Any]) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )

        return int(counted or 0)
