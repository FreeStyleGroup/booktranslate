"""Терминологический проход: от кандидатов к решённому словарю.

Порядок работы бюро, а не самодеятельность: сначала по книге собирается
список того, что в ней повторяется, потом список решается один раз — и
только потом начинается перевод. Слово, решённое до перевода, будет
одинаковым во всех сорока сегментах; слово, отданное модели на усмотрение,
одинаковым не будет никогда.

Решения хранятся, а не пересчитываются: отвергнутый кандидат больше не
показывается, иначе на повторном проходе редактор увидит те же двести
строк, включая уже разобранные, и второй раз этого не сделает.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.models.catalog import CatalogEntry
from app.models.document import Document
from app.models.memory import GlossaryEntryKind, GlossaryTermStatus
from app.models.project import Project
from app.models.segment import Segment
from app.models.terminology import TermCandidate, TermCandidateStatus
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
    expand_on_first_use: bool | None = None


@dataclass(slots=True)
class DecisionReport:
    accepted: int
    rejected: int
    # Сколько кандидатов ещё ждёт решения. Пока их больше нуля, документ
    # к переводу не готов.
    remaining: int


class TerminologyService(TenantService):
    async def extract(
        self, document_id: uuid.UUID, *, min_frequency: int = 2, limit: int = 400
    ) -> list[TermCandidate]:
        """Пройти по документу и обновить список кандидатов.

        Повторный проход не сбрасывает работу: принятое и отклонённое
        остаётся как есть, у кандидатов без решения обновляются частота и
        пример. Кандидат, которого в тексте больше нет (документ разобрали
        заново из другого файла), удаляется — но только если по нему не
        принимали решения: решение человека переживает переразбор.
        """
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

        candidates = extraction.extract(
            [segment.source_text for segment in segments],
            min_frequency=min_frequency,
            limit=limit,
        )

        # Извлечение считает по порядку в переданном списке и не знает про
        # нумерацию сегментов; здесь номер первого вхождения возвращается к
        # тому виду, в котором на него ссылаются в реестре.
        positions = [segment.position for segment in segments]

        existing = {
            row.source_term_normalized: row
            for row in await self._session.scalars(
                self.scoped(TermCandidate).where(TermCandidate.document_id == document.id)
            )
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
            row = existing.get(key)

            if row is None:
                self._session.add(
                    TermCandidate(
                        organization_id=self.organization_id,
                        document_id=document.id,
                        source_term=candidate.source,
                        source_term_normalized=key,
                        kind=candidate.kind,
                        status=TermCandidateStatus.NEW,
                        frequency=candidate.frequency,
                        sample=candidate.sample,
                        expansion=candidate.expansion,
                        first_position=positions[candidate.first_index],
                    )
                )
                continue

            row.frequency = candidate.frequency
            row.sample = candidate.sample
            row.first_position = positions[candidate.first_index]
            # Расшифровка, найденная однажды, не теряется: в новой редакции
            # книги автор мог её не повторить.
            row.expansion = candidate.expansion or row.expansion

            if row.status is TermCandidateStatus.NEW:
                row.kind = candidate.kind
                row.source_term = candidate.source

        for key, row in existing.items():
            if key not in seen and row.status is TermCandidateStatus.NEW:
                await self._session.delete(row)

        await self._session.commit()

        return await self.list(document.id)

    async def list(
        self,
        document_id: uuid.UUID,
        *,
        status: TermCandidateStatus | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TermCandidate]:
        query = self.scoped(TermCandidate).where(TermCandidate.document_id == document_id)

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

    # Sequence, а не list: имя `list` в теле класса уже занято методом выше,
    # и аннотация `list[Decision]` разобралась бы как обращение к нему.
    async def decide(self, document_id: uuid.UUID, decisions: Sequence[Decision]) -> DecisionReport:
        """Применить решения пачкой.

        Пачкой, а не по одному: двести кандидатов — это одна операция
        человека, и разваливать её на двести запросов значит получить
        наполовину решённый словарь, если связь оборвётся посередине.
        Транзакция одна: либо принято всё, либо ничего.
        """
        self._context.require(*EDITING_ROLES)

        if not decisions:
            return DecisionReport(0, 0, await self.undecided(document_id))

        document = await self._document(document_id)
        project = await self._session.scalar(
            self.scoped(Project).where(Project.id == document.project_id)
        )
        if project is None:
            raise NotFoundError("Проект не найден")

        glossary = GlossaryService(self._session, self._context)
        # Адреса, по которым термины смотрели в каталоге. Забираются заранее
        # одним запросом: справка, добытая поиском, обязана уехать в словарь
        # вместе с решением — потерять её в этот момент значит через месяц
        # начать спор о термине заново.
        sources = await self._catalog_sources(
            document.id,
            source_language=project.source_language,
            target_language=project.target_language,
        )
        accepted = 0
        rejected = 0

        for decision in decisions:
            row = await self._session.scalar(
                self.scoped(TermCandidate).where(
                    TermCandidate.id == decision.candidate_id,
                    TermCandidate.document_id == document.id,
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
                source_language=project.source_language,
                target_language=project.target_language,
                # Термины книги принадлежат её проекту, а не всему бюро:
                # у другого заказчика тот же `valve` — «вентиль».
                project_id=document.project_id,
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
                expand_on_first_use=self._expand_for(decision, kind),
                commit=False,
            )

            row.status = TermCandidateStatus.ACCEPTED
            row.glossary_term_id = term.id
            accepted += 1

        await self._session.commit()

        return DecisionReport(accepted, rejected, await self.undecided(document.id))

    async def _catalog_sources(
        self, document_id: uuid.UUID, *, source_language: str, target_language: str
    ) -> dict[str, str]:
        """Адреса источников из каталога по терминам этого документа.

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
                TermCandidate.document_id == document_id,
                CatalogEntry.source_language == source_language,
                CatalogEntry.target_language == target_language,
                CatalogEntry.found.is_(True),
            )
        )

        found = {}

        for row in rows:
            url = first_url(row)

            if url is not None:
                found[row.source_term_normalized] = url

        return found

    async def undecided(self, document_id: uuid.UUID) -> int:
        """Сколько кандидатов ждёт решения."""
        rows = await self._session.scalars(
            self.scoped(TermCandidate).where(
                TermCandidate.document_id == document_id,
                TermCandidate.status == TermCandidateStatus.NEW,
            )
        )

        return len(rows.all())

    @staticmethod
    def _expand_for(decision: Decision, kind: GlossaryEntryKind) -> bool:
        """Раскрывать ли запись при первом употреблении.

        Для аббревиатуры это правило технического текста: «маркет-мейкер
        (market maker, MM)», дальше просто MM. Читатель, встретивший MM без
        расшифровки, идёт искать её в интернете — и это провал перевода, а
        не читателя.
        """
        if decision.expand_on_first_use is not None:
            return decision.expand_on_first_use

        return kind is GlossaryEntryKind.ABBREVIATION

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

    async def _document(self, document_id: uuid.UUID) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        return document
