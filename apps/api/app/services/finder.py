"""Общий поиск по кабинету: файлы, словарь, каталог справок, текст книг.

Один запрос — четыре ответа. Человек, набравший «клапан» в шапке, не знает
заранее, где это слово лежит: в названии книги, в словаре, в справке или
в тексте на странице сорок. Спрашивать его об этом до поиска значит не
найти вовсе; вместо этого ищется везде, а группы показываются по очереди.

Поиск по подстроке, без морфологии и без полнотекстового индекса: на
объёмах бюро — тысячи терминов, десятки тысяч блоков — `ILIKE` по
индексированной организации отвечает за доли секунды, а полнотекстовый
поиск с русской морфологией — отдельная работа, которую стоит делать,
когда подстрока перестанет находить.

Из каждой группы берётся немного, а общее число считается отдельно: по
нему видно, что «ещё сорок блоков» есть, и куда за ними идти.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, or_, select

from app.models.block import Block
from app.models.book import BookEdition
from app.models.catalog import CatalogEntry
from app.models.chapter import Chapter
from app.models.document import Document
from app.models.memory import GlossaryTerm
from app.models.translation import TranslationRevision
from app.services.base import TenantService
from app.services.search import ESCAPE, contains

# Короче двух знаков — это не поиск, а перебор всей базы по одной букве.
MIN_QUERY = 2


@dataclass(slots=True)
class BlockHit:
    """Блок вместе с книгой и главой: без них строка ни о чём."""

    block: Block
    chapter: Chapter
    book_title: str
    translation: str | None


@dataclass(slots=True)
class Group[T]:
    total: int
    items: list[T] = field(default_factory=list)


@dataclass(slots=True)
class Found:
    documents: Group[Document]
    terms: Group[GlossaryTerm]
    entries: Group[CatalogEntry]
    blocks: Group[BlockHit]


class Finder(TenantService):
    async def find(self, query: str, *, per_group: int = 5) -> Found:
        pattern = contains(query)

        return Found(
            documents=await self._documents(pattern, per_group),
            terms=await self._terms(pattern, per_group),
            entries=await self._entries(pattern, per_group),
            blocks=await self._blocks(pattern, per_group),
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

    async def _blocks(self, pattern: str, limit: int) -> Group[BlockHit]:
        """Блоки — по исходнику и по текущей редакции, с книгой и главой.

        Свежие книги первыми, внутри главы — по порядку: человек, ищущий фразу, чаще
        всего ищет её в том, над чем работает сейчас.
        """
        condition = (
            Block.organization_id == self.organization_id,
            Block.active.is_(True),
            or_(
                Block.source_text.ilike(pattern, escape=ESCAPE),
                TranslationRevision.text.ilike(pattern, escape=ESCAPE),
            ),
        )

        counted = await self._session.scalar(
            select(func.count())
            .select_from(Block)
            .outerjoin(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(*condition)
        )

        rows = await self._session.execute(
            select(Block, Chapter, BookEdition.title, TranslationRevision.text)
            .join(Chapter, Chapter.id == Block.chapter_id)
            .join(BookEdition, BookEdition.id == Chapter.book_id)
            .outerjoin(TranslationRevision, TranslationRevision.id == Block.current_revision_id)
            .where(*condition)
            .order_by(BookEdition.updated_at.desc(), Chapter.ordinal, Block.ordinal)
            .limit(limit)
        )

        return Group(
            total=int(counted or 0),
            items=[
                BlockHit(block=block, chapter=chapter, book_title=title, translation=translation)
                for block, chapter, title, translation in rows
            ],
        )

    async def _count(self, statement: Select[Any]) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )

        return int(counted or 0)
