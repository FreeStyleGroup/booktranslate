"""Терминологический проход: от кандидатов к решённому словарю.

Порядок работы бюро, а не самодеятельность: сначала по книге собирается
список того, что в ней повторяется, потом список решается один раз — и
только потом начинается перевод. Слово, решённое до перевода, будет
одинаковым во всех сорока блоках; слово, отданное модели на усмотрение,
одинаковым не будет никогда.

Решения хранятся, а не пересчитываются: отвергнутый кандидат больше не
показывается, иначе на повторном проходе редактор увидит те же двести
строк, включая уже разобранные, и второй раз этого не сделает.

Проход идёт по главе — по тексту её текущего мастера — и записывается:
версия глоссария утверждается только по главам, где проход был, и был по
нынешнему тексту. Проход по документу остался от прежнего контура и
уходит вместе с сегментами; правила решений у обоих общие.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.models.block import Block, BlockKind
from app.models.book import BookEdition
from app.models.catalog import CatalogEntry
from app.models.chapter import Chapter
from app.models.document import Document
from app.models.master import ChapterMaster
from app.models.memory import FirstUseRule, GlossaryEntryKind, GlossaryTermStatus
from app.models.project import Project
from app.models.segment import Segment
from app.models.terminology import TermCandidate, TermCandidateStatus, TerminologyPass
from app.services import extraction
from app.services.base import TenantService
from app.services.catalog import first_url
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.glossary import EDITING_ROLES, GlossaryService, normalize_term

# Термины, вытащенные из самого документа, отмечаются так. По этой метке их
# отличают и от ручной работы, и от загруженной внешней базы.
EXTRACTED = "extracted"


@dataclass(slots=True)
class Decision:
    """Решение человека по одному кандидату."""

    candidate_id: uuid.UUID
    accept: bool
    target_term: str | None = None
    # Вид можно поправить: извлечение относит к терминам всё, что не похоже
    # на аббревиатуру или стандарт, и иногда ошибается в обе стороны.
    kind: GlossaryEntryKind | None = None
    mandatory: bool = True
    note: str | None = None
    # Чем решение обосновано: справочник, стандарт, адрес страницы.
    reference: str | None = None
    # Насколько решение устоялось. По умолчанию подтверждено: человек,
    # набравший перевод, уже договорился с собой. Бюро с двумя проходами по
    # словарю ставит здесь PROPOSED и подтверждает вторым проходом.
    status: GlossaryTermStatus = GlossaryTermStatus.CONFIRMED
    # None означает «по умолчанию для вида»: аббревиатуру при первом
    # употреблении принято раскрывать, обычный термин — нет.
    first_use_rule: FirstUseRule | None = None
    allowed_variants: list[str] = field(default_factory=list)
    domain: str | None = None


@dataclass(slots=True)
class DecisionReport:
    accepted: int
    rejected: int
    # Сколько кандидатов ещё ждёт решения. Пока их больше нуля, терминология
    # не готова.
    remaining: int


@dataclass(frozen=True, slots=True)
class _Owner:
    """Чьи кандидаты: документа прежнего контура или главы.

    Колонка и значение вместе — чтобы отбор и новая строка не разошлись:
    кандидат главы, заведённый с колонкой документа, нарушил бы
    ограничение базы, а отбор по чужой колонке не нашёл бы своих.
    """

    column: InstrumentedAttribute[uuid.UUID | None]
    value: uuid.UUID

    @property
    def where(self) -> ColumnElement[bool]:
        return self.column == self.value

    @property
    def fields(self) -> dict[str, uuid.UUID]:
        return {self.column.key: self.value}


@dataclass(frozen=True, slots=True)
class _Place:
    """Где в тексте владельца стоит кусок, по которому ищут термины."""

    position: int
    block_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class _Pair:
    """Куда уходят принятые термины: проект и языковая пара."""

    project_id: uuid.UUID
    source_language: str
    target_language: str


class TerminologyService(TenantService):
    # ── глава ──────────────────────────────────────────────────────────

    async def extract_chapter(
        self, chapter_id: uuid.UUID, *, min_frequency: int = 2, limit: int = 400
    ) -> list[TermCandidate]:
        """Пройти по тексту текущего мастера главы и обновить кандидатов.

        Листинги в проход не идут: код переносится побайтно, и его
        идентификаторы — не термины, которые решают, а строки, которые не
        трогают. Проход записывается вместе с версией мастера: по этой
        записи видно, что термины главы собраны, и собраны по её нынешнему
        тексту.

        Слово, которое уже есть в словаре проекта книги, приходит решённым:
        решение о термине принимается для книги один раз, и спрашивать о
        «relief valve» в каждой из двадцати глав — значит получить двадцать
        шансов назвать его по-разному.
        """
        self._context.require(*EDITING_ROLES)

        # Строка главы блокируется: два прохода по одной главе разом
        # завели бы одного кандидата дважды и упали на уникальности.
        chapter = await self._chapter(chapter_id, lock=True)
        master = await self._current_master(chapter.id)

        if master is None:
            raise ConflictError("У главы ещё нет мастера — сначала извлеките её текст")

        book = await self._book(chapter.book_id)
        known = {
            row.source_term_normalized: row.id
            for row in await GlossaryService(self._session, self._context).own_terms(
                project_id=book.project_id,
                source_language=book.source_language,
                target_language=book.target_language,
            )
        }

        order = {uuid.UUID(value): place for place, value in enumerate(master.block_ids)}
        blocks = sorted(
            await self._session.scalars(
                self.scoped(Block).where(Block.id.in_(order), Block.kind != BlockKind.CODE)
            ),
            key=lambda block: order[block.id],
        )

        found = await self._refresh(
            _Owner(TermCandidate.chapter_id, chapter.id),
            texts=[block.source_text for block in blocks],
            places=[_Place(order[block.id], block.id) for block in blocks],
            min_frequency=min_frequency,
            limit=limit,
            known=known,
        )

        self._session.add(
            TerminologyPass(
                organization_id=self.organization_id,
                chapter_id=chapter.id,
                master_id=master.id,
                actor_id=self._context.user.id,
                min_frequency=min_frequency,
                found=found,
            )
        )
        await self._session.commit()

        return await self.chapter_candidates(chapter.id)

    async def chapter_candidates(
        self,
        chapter_id: uuid.UUID,
        *,
        status: TermCandidateStatus | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TermCandidate]:
        chapter = await self._chapter(chapter_id)

        return await self._list(
            _Owner(TermCandidate.chapter_id, chapter.id), status=status, limit=limit, offset=offset
        )

    async def first_codes(
        self, chapter_id: uuid.UUID, candidates: Sequence[TermCandidate]
    ) -> dict[uuid.UUID, str]:
        """Коды блоков первого вхождения: `CH03-B0042` у каждого кандидата."""
        chapter = await self._chapter(chapter_id)
        wanted = {item.first_block_id for item in candidates if item.first_block_id is not None}

        if not wanted:
            return {}

        prefix = f"{chapter.code}-" if chapter.code is not None else ""
        blocks = {
            block.id: block
            for block in await self._session.scalars(self.scoped(Block).where(Block.id.in_(wanted)))
        }

        return {
            item.id: prefix + blocks[item.first_block_id].code
            for item in candidates
            if item.first_block_id is not None and item.first_block_id in blocks
        }

    async def decide_chapter(
        self, chapter_id: uuid.UUID, decisions: Sequence[Decision]
    ) -> DecisionReport:
        """Решения по кандидатам главы: принятые уходят в словарь проекта книги."""
        self._context.require(*EDITING_ROLES)

        chapter = await self._chapter(chapter_id)
        book = await self._book(chapter.book_id)

        # Пара — у книги, а не у проекта: в проекте бывают книги с другой
        # целевой парой, и термин, решённый для одной, другой не годится.
        return await self._decide(
            _Owner(TermCandidate.chapter_id, chapter.id),
            decisions,
            _Pair(book.project_id, book.source_language, book.target_language),
        )

    async def undecided_by_chapter(self, chapter_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Сколько кандидатов ждёт решения в каждой главе — одним запросом."""
        if not chapter_ids:
            return {}

        rows = await self._session.execute(
            select(TermCandidate.chapter_id, func.count())
            .where(
                TermCandidate.organization_id == self.organization_id,
                TermCandidate.chapter_id.in_(chapter_ids),
                TermCandidate.status == TermCandidateStatus.NEW,
            )
            .group_by(TermCandidate.chapter_id)
        )

        return {chapter_id: count for chapter_id, count in rows.tuples() if chapter_id is not None}

    async def passes_over(
        self, master_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, TerminologyPass]:
        """Проход по каждой из этих версий мастера — свежий из бывших.

        Отбор по версии мастера, а не «последний по главе»: важно не то,
        какой проход был последним, а был ли проход по нынешнему тексту.
        Время прохода — время его транзакции, и у двух проходов одной
        транзакции оно одинаковое; на нём держать решение нельзя.
        """
        if not master_ids:
            return {}

        rows = await self._session.scalars(
            self.scoped(TerminologyPass)
            .where(TerminologyPass.master_id.in_(master_ids))
            .order_by(TerminologyPass.master_id, TerminologyPass.created_at.desc())
            .distinct(TerminologyPass.master_id)
        )

        return {row.master_id: row for row in rows}

    # ── документ прежнего контура ──────────────────────────────────────

    async def extract(
        self, document_id: uuid.UUID, *, min_frequency: int = 2, limit: int = 400
    ) -> list[TermCandidate]:
        """Пройти по сегментам документа и обновить список кандидатов."""
        self._context.require(*EDITING_ROLES)

        document = await self._document(document_id)

        segments = list(
            await self._session.scalars(
                self.scoped(Segment)
                .where(Segment.document_id == document.id)
                .order_by(Segment.position)
            )
        )
        if not segments:
            raise ConflictError("Документ ещё не разобран на сегменты")

        await self._refresh(
            _Owner(TermCandidate.document_id, document.id),
            texts=[segment.source_text for segment in segments],
            places=[_Place(segment.position) for segment in segments],
            min_frequency=min_frequency,
            limit=limit,
        )
        await self._session.commit()

        return await self.document_candidates(document.id)

    async def document_candidates(
        self,
        document_id: uuid.UUID,
        *,
        status: TermCandidateStatus | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TermCandidate]:
        return await self._list(
            _Owner(TermCandidate.document_id, document_id),
            status=status,
            limit=limit,
            offset=offset,
        )

    async def decide(self, document_id: uuid.UUID, decisions: Sequence[Decision]) -> DecisionReport:
        """Применить решения по кандидатам документа."""
        self._context.require(*EDITING_ROLES)

        owner = _Owner(TermCandidate.document_id, document_id)

        if not decisions:
            return DecisionReport(0, 0, await self._undecided(owner))

        document = await self._document(document_id)
        project = await self._session.scalar(
            self.scoped(Project).where(Project.id == document.project_id)
        )
        if project is None:
            raise NotFoundError("Проект не найден")

        return await self._decide(
            owner,
            decisions,
            _Pair(project.id, project.source_language, project.target_language),
        )

    async def undecided(self, document_id: uuid.UUID) -> int:
        """Сколько кандидатов документа ждёт решения."""
        return await self._undecided(_Owner(TermCandidate.document_id, document_id))

    # ── общее ──────────────────────────────────────────────────────────

    async def _refresh(
        self,
        owner: _Owner,
        *,
        texts: list[str],
        places: list[_Place],
        min_frequency: int,
        limit: int,
        known: Mapping[str, uuid.UUID] | None = None,
    ) -> int:
        """Обновить кандидатов владельца по тексту; вернуть, сколько найдено.

        Повторный проход не сбрасывает работу: принятое и отклонённое
        остаётся как есть, у кандидатов без решения обновляются частота и
        пример. Кандидат, которого в тексте больше нет, удаляется — но
        только если по нему не принимали решения: решение человека
        переживает новый текст.

        `known` — термины, уже решённые в словаре, и их записи: такой
        кандидат приходит принятым, со ссылкой на решение.
        """
        known = known or {}
        candidates = extraction.extract(texts, min_frequency=min_frequency, limit=limit)

        existing = {
            row.source_term_normalized: row
            for row in await self._session.scalars(self.scoped(TermCandidate).where(owner.where))
        }

        seen: set[str] = set()

        for candidate in candidates:
            key = normalize_term(candidate.source)

            # Одно и то же слово в разных написаниях — один кандидат:
            # уникальность в базе построена на нормализованном виде, и без
            # этой проверки вставка упала бы на конфликте.
            if key in seen:
                continue

            seen.add(key)
            # Извлечение считает по порядку в переданном списке; здесь
            # номер первого вхождения возвращается к тому виду, в котором
            # на него ссылаются люди.
            place = places[candidate.first_index]
            row = existing.get(key)

            decided = known.get(key)

            if row is None:
                self._session.add(
                    TermCandidate(
                        organization_id=self.organization_id,
                        **owner.fields,
                        source_term=candidate.source,
                        source_term_normalized=key,
                        kind=candidate.kind,
                        status=TermCandidateStatus.NEW
                        if decided is None
                        else TermCandidateStatus.ACCEPTED,
                        frequency=candidate.frequency,
                        sample=candidate.sample,
                        expansion=candidate.expansion,
                        first_position=place.position,
                        first_block_id=place.block_id,
                        glossary_term_id=decided,
                    )
                )
                continue

            row.frequency = candidate.frequency
            row.sample = candidate.sample
            row.first_position = place.position
            row.first_block_id = place.block_id
            # Расшифровка, найденная однажды, не теряется: в новой редакции
            # книги автор мог её не повторить.
            row.expansion = candidate.expansion or row.expansion

            if row.status is TermCandidateStatus.NEW:
                row.kind = candidate.kind
                row.source_term = candidate.source

                # Пока кандидат ждал, термин решили в другой главе.
                if decided is not None:
                    row.status = TermCandidateStatus.ACCEPTED
                    row.glossary_term_id = decided

        for key, row in existing.items():
            if key not in seen and row.status is TermCandidateStatus.NEW:
                await self._session.delete(row)

        return len(seen)

    async def _list(
        self, owner: _Owner, *, status: TermCandidateStatus | None, limit: int, offset: int
    ) -> list[TermCandidate]:
        query = self.scoped(TermCandidate).where(owner.where)

        if status is not None:
            query = query.where(TermCandidate.status == status)

        # Сортировка по статусу опирается на порядок значений перечисления в
        # Postgres, а он совпадает с порядком объявления: NEW, ACCEPTED,
        # REJECTED. То есть нерешённое идёт первым — ровно то, что нужно
        # человеку, открывшему список.
        query = query.order_by(
            TermCandidate.status,
            TermCandidate.frequency.desc(),
            TermCandidate.source_term_normalized,
        )

        return list(await self._session.scalars(query.limit(limit).offset(offset)))

    async def _decide(
        self, owner: _Owner, decisions: Sequence[Decision], pair: _Pair
    ) -> DecisionReport:
        """Применить решения пачкой.

        Пачкой, а не по одному: двести кандидатов — это одна операция
        человека, и разваливать её на двести запросов значит получить
        наполовину решённый словарь, если связь оборвётся посередине.
        Транзакция одна: либо принято всё, либо ничего.
        """
        if not decisions:
            return DecisionReport(0, 0, await self._undecided(owner))

        glossary = GlossaryService(self._session, self._context)
        # Адреса, по которым термины смотрели в каталоге. Забираются заранее
        # одним запросом: справка, добытая поиском, обязана уехать в словарь
        # вместе с решением — потерять её в этот момент значит через месяц
        # начать спор о термине заново.
        sources = await self._catalog_sources(owner, pair)
        accepted = 0
        rejected = 0

        for decision in decisions:
            row = await self._session.scalar(
                self.scoped(TermCandidate).where(
                    TermCandidate.id == decision.candidate_id, owner.where
                )
            )
            if row is None:
                raise NotFoundError("Кандидат не найден")

            if not decision.accept:
                row.status = TermCandidateStatus.REJECTED
                row.glossary_term_id = None
                rejected += 1
                continue

            kind = decision.kind or row.kind
            term = await glossary.add(
                source_term=row.source_term,
                target_term=self._target_for(row, decision, kind),
                source_language=pair.source_language,
                target_language=pair.target_language,
                # Термины книги принадлежат её проекту, а не всему бюро:
                # у другого заказчика тот же `valve` — «вентиль».
                project_id=pair.project_id,
                # Расшифровка из текста идёт в примечание: переводчик,
                # знающий, что за PLC, не напишет «ПЛК-контроллер».
                note=decision.note or row.expansion,
                mandatory=decision.mandatory,
                source=EXTRACTED,
                kind=kind,
                status=decision.status,
                # Присланное человеком важнее: он мог посмотреть термин в
                # бумажном справочнике, которого в каталоге нет.
                reference=decision.reference or sources.get(row.source_term_normalized),
                first_use_rule=self._first_use_for(decision, kind),
                allowed_variants=decision.allowed_variants,
                domain=decision.domain,
                commit=False,
            )

            row.status = TermCandidateStatus.ACCEPTED
            row.glossary_term_id = term.id
            accepted += 1

        await self._session.commit()

        return DecisionReport(accepted, rejected, await self._undecided(owner))

    async def _catalog_sources(self, owner: _Owner, pair: _Pair) -> dict[str, str]:
        """Адреса источников из каталога по терминам владельца.

        Один запрос на всю пачку решений, а не по запросу на кандидата:
        решений двести, и двести походов в базу ради поля «источник» — это
        секунды на ровном месте.
        """
        rows = await self._session.scalars(
            self.scoped(CatalogEntry)
            .join(
                TermCandidate,
                TermCandidate.source_term_normalized == CatalogEntry.source_term_normalized,
            )
            .where(
                owner.where,
                CatalogEntry.source_language == pair.source_language,
                CatalogEntry.target_language == pair.target_language,
                CatalogEntry.found.is_(True),
            )
        )

        found = {}

        for row in rows:
            url = first_url(row)

            if url is not None:
                found[row.source_term_normalized] = url

        return found

    async def _undecided(self, owner: _Owner) -> int:
        counted = await self._session.scalar(
            select(func.count()).where(
                TermCandidate.organization_id == self.organization_id,
                owner.where,
                TermCandidate.status == TermCandidateStatus.NEW,
            )
        )

        return int(counted or 0)

    @staticmethod
    def _first_use_for(decision: Decision, kind: GlossaryEntryKind) -> FirstUseRule:
        """Что делать с записью при первом употреблении.

        Для аббревиатуры правило технического текста — раскрыть:
        «маркет-мейкер (market maker, MM)», дальше просто MM. Читатель,
        встретивший MM без расшифровки, идёт искать её в интернете — и это
        провал перевода, а не читателя.
        """
        if decision.first_use_rule is not None:
            return decision.first_use_rule

        return FirstUseRule.EXPAND if kind is GlossaryEntryKind.ABBREVIATION else FirstUseRule.NONE

    @staticmethod
    def _target_for(row: TermCandidate, decision: Decision, kind: GlossaryEntryKind) -> str:
        target = (decision.target_term or "").strip()

        if target:
            return target

        # У непереводимого перевод совпадает с исходником по определению,
        # и требовать его от человека — заставлять копировать строку.
        if kind is GlossaryEntryKind.DO_NOT_TRANSLATE:
            return row.source_term

        raise InvalidInputError(f"Для термина «{row.source_term}» нужен перевод")

    async def _chapter(self, chapter_id: uuid.UUID, *, lock: bool = False) -> Chapter:
        query = self.scoped(Chapter).where(Chapter.id == chapter_id)
        chapter = await self._session.scalar(query.with_for_update() if lock else query)

        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _book(self, book_id: uuid.UUID) -> BookEdition:
        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))

        if book is None:
            raise NotFoundError("Книга не найдена")

        return book

    async def _current_master(self, chapter_id: uuid.UUID) -> ChapterMaster | None:
        master: ChapterMaster | None = await self._session.scalar(
            self.scoped(ChapterMaster)
            .where(ChapterMaster.chapter_id == chapter_id)
            .order_by(ChapterMaster.version.desc())
            .limit(1)
        )

        return master

    async def _document(self, document_id: uuid.UUID) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        return document
