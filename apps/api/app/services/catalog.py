"""Каталог терминов: справки, которые бюро накапливает за собой.

Незнакомое слово смотрят один раз. Дальше оно уже известно — и в этой книге,
и в следующей, и через год в чужом проекте той же организации. Ради этого
каталог и заведён: без него за одну и ту же справку платят столько раз,
сколько раз слово попадётся в работе, а переводчик каждый раз выясняет то,
что коллега выяснил в прошлом месяце.

Каталог общий для организации, а не проектный. Что такое `basis risk`, от
заказчика не зависит; от заказчика зависит, как это называть, — и это уже
решение, оно живёт в словаре (`app/services/glossary.py`).

**Справка ничего не решает.** Она не заводит терминов и не подтверждает
переводов: человек видит определение, предложение и адреса источников и
принимает решение сам. Автоматическая запись найденного в словарь свела бы
на нет весь терминологический проход — слово, попавшее туда без проверки,
разойдётся по всей книге и будет выглядеть согласованным.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.catalog import CatalogEntry
from app.models.document import Document
from app.models.project import Project
from app.models.terminology import TermCandidate, TermCandidateStatus
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import InvalidInputError, NotFoundError
from app.services.glossary import EDITING_ROLES, normalize_term
from app.services.providers import Explanation, LookupRequest, TermLookupProvider, Usage

# Сколько знаков отрывка уходит в запрос. Отрывок нужен, чтобы отличить
# отрасль, а не чтобы пересказать главу.
MAX_SAMPLE = 400


@dataclass(slots=True)
class Unknown:
    """Слово, про которое спрашивают."""

    source_term: str
    sample: str = ""


@dataclass(slots=True)
class LookupReport:
    """Чем закончился прогон по списку.

    Разделение на «взято из каталога» и «спрошено заново» — не статистика:
    это ровно то, ради чего каталог существует, и по нему видно, окупается
    ли он.
    """

    entries: list[CatalogEntry] = field(default_factory=list)
    from_catalog: int = 0
    asked: int = 0
    found: int = 0

    # Расход прогона. На документ он не относится: справка достаётся всем
    # книгам организации, и записать её стоимость на ту, где слово попалось
    # первым, значит завысить одну книгу и занизить остальные.
    usage: Usage = field(default_factory=Usage)
    searches: int = 0


class CatalogService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, lookup: TermLookupProvider
    ) -> None:
        super().__init__(session, context)
        self._lookup = lookup

    async def explain(
        self,
        unknowns: Sequence[Unknown],
        *,
        source_language: str,
        target_language: str,
        subject: str | None = None,
        refresh: bool = False,
    ) -> LookupReport:
        """Собрать справки по списку слов.

        Сначала каталог, потом сеть: уже выясненное не спрашивается заново.
        `refresh` заставляет спросить снова — например когда справку получили
        до того, как стало ясно, о какой отрасли идёт речь.
        """
        self._context.require(*EDITING_ROLES)

        wanted = self._unique(unknowns)
        if not wanted:
            return LookupReport()

        limit = get_settings().term_lookup_batch
        if len(wanted) > limit:
            raise InvalidInputError(f"За раз ищется не больше {limit} терминов")

        known = await self._known(
            list(wanted), source_language=source_language, target_language=target_language
        )

        pending = [unknown for key, unknown in wanted.items() if refresh or key not in known]

        answers = await self._ask(
            pending,
            source_language=source_language,
            target_language=target_language,
            subject=subject,
        )

        report = LookupReport(from_catalog=len(wanted) - len(pending), asked=len(pending))

        for unknown, explanation in zip(pending, answers, strict=True):
            key = normalize_term(unknown.source_term)
            known[key] = self._store(
                known.get(key),
                unknown=unknown,
                explanation=explanation,
                source_language=source_language,
                target_language=target_language,
            )
            report.usage = report.usage + explanation.usage
            report.searches += explanation.searches

        await self._session.commit()

        report.entries = [known[key] for key in wanted if key in known]
        report.found = sum(1 for entry in report.entries if entry.found)

        return report

    async def explain_document(
        self,
        document_id: uuid.UUID,
        *,
        candidate_ids: Sequence[uuid.UUID] | None = None,
        limit: int | None = None,
        refresh: bool = False,
    ) -> LookupReport:
        """Разобраться с нерешёнными кандидатами документа.

        Берутся самые частые из нерешённых: слово, встреченное сорок раз,
        стоит справки больше, чем случайное из подписи к рисунку. Отрывок из
        книги уходит в запрос вместе с термином — одно и то же слово в разных
        отраслях значит разное.
        """
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        project = await self._session.scalar(
            self.scoped(Project).where(Project.id == document.project_id)
        )
        if project is None:
            raise NotFoundError("Проект не найден")

        query = self.scoped(TermCandidate).where(TermCandidate.document_id == document.id)

        if candidate_ids:
            query = query.where(TermCandidate.id.in_(list(candidate_ids)))
        else:
            # Без явного списка спрашиваем только про нерешённое: по
            # разобранному справка уже не нужна, а деньги стоит.
            query = query.where(TermCandidate.status == TermCandidateStatus.NEW)

        query = query.order_by(TermCandidate.frequency.desc(), TermCandidate.first_position)
        candidates = list(
            await self._session.scalars(query.limit(limit or get_settings().term_lookup_batch))
        )

        return await self.explain(
            [
                Unknown(source_term=row.source_term, sample=row.sample[:MAX_SAMPLE])
                for row in candidates
            ],
            source_language=project.source_language,
            target_language=project.target_language,
            # Название книги и проекта задаёт отрасль там, где отрывка мало.
            subject=f"{project.name}. {document.title}",
            refresh=refresh,
        )

    async def search(
        self, *, query: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[CatalogEntry]:
        """Просмотр каталога.

        Поиск идёт и по исходному слову, и по определению: человек помнит
        «что-то про проскальзывание цены» чаще, чем точное написание термина.
        """
        statement = self.scoped(CatalogEntry)

        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    CatalogEntry.source_term_normalized.ilike(pattern),
                    CatalogEntry.suggested_target.ilike(pattern),
                    CatalogEntry.definition.ilike(pattern),
                )
            )

        statement = statement.order_by(CatalogEntry.source_term_normalized)

        return list(await self._session.scalars(statement.limit(limit).offset(offset)))

    @staticmethod
    def _unique(unknowns: Sequence[Unknown]) -> dict[str, Unknown]:
        """Список без повторов, в порядке поступления.

        Повтор внутри одного запроса — не ошибка вызывающего, а обычное дело:
        `Valve` и `valve` для справки одно и то же, и спрашивать про них
        дважды значит платить дважды.
        """
        wanted: dict[str, Unknown] = {}

        for unknown in unknowns:
            key = normalize_term(unknown.source_term)

            if key and key not in wanted:
                wanted[key] = unknown

        return wanted

    async def _known(
        self, keys: Sequence[str], *, source_language: str, target_language: str
    ) -> dict[str, CatalogEntry]:
        rows = await self._session.scalars(
            self.scoped(CatalogEntry).where(
                CatalogEntry.source_language == source_language,
                CatalogEntry.target_language == target_language,
                CatalogEntry.source_term_normalized.in_(list(keys)),
            )
        )

        return {row.source_term_normalized: row for row in rows}

    async def _ask(
        self,
        pending: Sequence[Unknown],
        *,
        source_language: str,
        target_language: str,
        subject: str | None,
    ) -> list[Explanation]:
        """Спросить внешний источник про то, чего нет в каталоге.

        Запросы идут одновременно, но не все сразу: поиск занимает секунды, и
        по одному пришлось бы ждать минутами, а всеми сразу — упереться в
        ограничение частоты и получить отказ по всей пачке.

        В базу при этом ничего не пишется: сессия одна на запрос и не
        рассчитана на одновременную работу.
        """
        if not pending:
            return []

        limit = asyncio.Semaphore(get_settings().term_lookup_concurrency)

        async def one(unknown: Unknown) -> Explanation:
            async with limit:
                return await self._lookup.lookup(
                    LookupRequest(
                        source_term=unknown.source_term,
                        source_language=source_language,
                        target_language=target_language,
                        sample=unknown.sample,
                        subject=subject,
                    )
                )

        return list(await asyncio.gather(*(one(unknown) for unknown in pending)))

    def _store(
        self,
        entry: CatalogEntry | None,
        *,
        unknown: Unknown,
        explanation: Explanation,
        source_language: str,
        target_language: str,
    ) -> CatalogEntry:
        """Записать справку в каталог — новую либо поверх устаревшей."""
        if entry is None:
            entry = CatalogEntry(
                organization_id=self.organization_id,
                source_language=source_language,
                target_language=target_language,
                source_term=unknown.source_term.strip(),
                source_term_normalized=normalize_term(unknown.source_term),
            )
            self._session.add(entry)

        entry.found = explanation.found
        entry.suggested_target = explanation.suggested_target
        entry.definition = explanation.definition
        entry.expansion = explanation.expansion
        entry.kind = explanation.kind
        entry.sources = [
            {"title": reference.title, "url": reference.url} for reference in explanation.references
        ]
        entry.looked_up_by = self._lookup.name
        entry.checked_at = datetime.now(UTC)

        return entry


def first_url(entry: CatalogEntry) -> str | None:
    """Первый адрес источника справки, если он есть."""
    for reference in entry.sources or []:
        url = reference.get("url")

        if isinstance(url, str) and url:
            return url

    return None
