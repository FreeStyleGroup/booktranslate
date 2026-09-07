"""Перевод сегментов.

Цель — перевод, который можно отдать в печать, а не черновик подешевле.
Это решение (`docs/DECISIONS.md`): дешёвый прогон с последующей вычиткой
в техническом тексте не работает, потому что ошибки в нём терминологические
и видит их только тот, кто читал исходник. Править такое дороже, чем
переводить заново.

Отсюда весь порядок шагов: к моменту, когда сегмент уходит в модель, всё,
что можно было решить заранее, уже решено.

1. **Терминология решена до перевода.** Пока по документу остались
   нерешённые кандидаты, перевод не начинается: слово, отданное модели на
   усмотрение, в сорока сегментах будет названо по-разному.
2. **Одинаковые сегменты собираются вместе.** Не ради экономии, а ради
   того, чтобы повторяющееся предупреждение звучало в книге одинаково;
   то, что за него платят один раз, — приятное следствие.
3. **Память переводов.** То же самое между документами: вторая книга серии
   обязана называть вещи так же, как первая.
4. **Модель получает термины, встретившиеся в этом сегменте** — как
   ограничение, а не как справочный материал, — и соседние сегменты с
   заголовком раздела: без них «он», «указанный выше» и опущенное
   подлежащее переводятся наугад.
5. **Проверки на выходе.** Числа, подстановки, употребление терминов,
   раскрытие аббревиатуры при первом употреблении. Всё, что не сошлось,
   помечает сегмент и уходит к человеку.

Результат возвращается в память, поэтому следующий документ переводится
не только дешевле, но и согласованно с предыдущим.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.organization import Role
from app.models.project import Project
from app.models.segment import Segment, SegmentKind, SegmentStatus
from app.services import checks
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, NotFoundError
from app.services.glossary import Glossary, GlossaryService
from app.services.memory import TranslationMemory, fingerprint
from app.services.providers import (
    EMPTY_CONTEXT,
    Neighbourhood,
    TranslationProvider,
    TranslationRequest,
    Usage,
)
from app.services.terminology import TerminologyService

TRANSLATING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

MEMORY_SOURCE = "memory"


@dataclass(slots=True)
class TranslationSummary:
    """Чем закончился перевод. Отдаётся клиенту и годится для счёта денег."""

    total: int
    from_memory: int
    from_provider: int
    flagged: int
    unique_texts: int
    # Сколько текстов реально ушло провайдеру. Не то же самое, что
    # from_provider: тот считает СЕГМЕНТЫ, получившие перевод от модели, а
    # повторяющийся сегмент получает его, не стоив отдельного обращения.
    provider_calls: int

    # Потрачено на этот запуск. Ноль у заглушки — она ничего и не тратит.
    usage: Usage = field(default_factory=Usage)

    @property
    def saved_calls(self) -> int:
        """Сколько обращений к модели не понадобилось.

        Наивный перевод стоил бы одного обращения на сегмент. Разница с
        реальным числом обращений — это и есть то, за что не заплачено:
        повторы внутри документа плюс совпадения с памятью.
        """
        return self.total - self.provider_calls


class TranslationService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, provider: TranslationProvider
    ) -> None:
        super().__init__(session, context)
        self._provider = provider

    async def translate(
        self,
        document_id: uuid.UUID,
        *,
        force: bool = False,
        ignore_terminology: bool = False,
    ) -> TranslationSummary:
        self._context.require(*TRANSLATING_ROLES)

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        if document.status in (DocumentStatus.UPLOADED, DocumentStatus.PARSING):
            raise ConflictError("Документ ещё не разобран на сегменты")

        if not ignore_terminology:
            # Терминологический проход либо не запускался (тогда кандидатов
            # нет и проверка молчит), либо запускался и не доведён до конца.
            # Второе — это перевод поверх нерешённого словаря, ровно та
            # ошибка, ради которой проход и заводился.
            remaining = await TerminologyService(self._session, self._context).undecided(
                document.id
            )
            if remaining:
                raise ConflictError(
                    f"Терминологический проход не закончен: {remaining} кандидатов без решения"
                )

        project = await self._session.scalar(
            self.scoped(Project).where(Project.id == document.project_id)
        )
        if project is None:
            raise NotFoundError("Проект не найден")

        segments = await self._segments(document_id, force=force)
        if not segments:
            return TranslationSummary(0, 0, 0, 0, 0, 0)

        glossary = await GlossaryService(self._session, self._context).load(
            project_id=document.project_id,
            source_language=project.source_language,
            target_language=project.target_language,
        )

        document.status = DocumentStatus.TRANSLATING
        await self._session.commit()

        summary = await self._run(
            segments,
            glossary=glossary,
            source_language=project.source_language,
            target_language=project.target_language,
        )

        # REVIEW, а не DONE: перевод сделан, но принимает его человек.
        document.status = DocumentStatus.REVIEW
        await self._session.commit()

        return summary

    async def _segments(self, document_id: uuid.UUID, *, force: bool) -> list[Segment]:
        query = self.scoped(Segment).where(Segment.document_id == document_id)

        if not force:
            # Правку человека и принятые сегменты повторный запуск не трогает:
            # перевести заново то, что уже вычитано, значит выбросить работу.
            query = query.where(Segment.status == SegmentStatus.NEW)

        return list(await self._session.scalars(query.order_by(Segment.position)))

    async def _run(
        self,
        segments: list[Segment],
        *,
        glossary: Glossary,
        source_language: str,
        target_language: str,
    ) -> TranslationSummary:
        memory = TranslationMemory(self._session, self._context)

        # Одинаковые сегменты собираются вместе: переводится один, результат
        # получают все. Ключ — отпечаток, а не текст: сегменты, различающиеся
        # только пробелами, для перевода одинаковы.
        groups: dict[str, list[Segment]] = {}
        for segment in segments:
            groups.setdefault(fingerprint(segment.source_text), []).append(segment)

        known = await memory.lookup(
            [group[0].source_text for group in groups.values()],
            source_language=source_language,
            target_language=target_language,
        )

        from_memory = 0
        used_units: list[uuid.UUID] = []
        pending: list[tuple[str, list[Segment]]] = []

        for digest, group in groups.items():
            unit = known.get(digest)
            if unit is None:
                pending.append((digest, group))
                continue

            for segment in group:
                self._apply(
                    segment, unit.target_text, MEMORY_SOURCE, SegmentStatus.MEMORY, glossary
                )
                from_memory += 1

            used_units.append(unit.id)

        translated, spent = await self._call_provider(
            pending,
            glossary=glossary,
            # Соседи нужны только тому, что уходит модели: подстановка из
            # памяти в контексте не нуждается, и лишний проход по документу
            # ради неё делать незачем.
            context=await self._neighbourhood(segments[0].document_id) if pending else {},
            source_language=source_language,
            target_language=target_language,
        )

        await memory.count_hits(used_units)
        await memory.remember(
            translated,
            source_language=source_language,
            target_language=target_language,
            origin=self._provider.name,
        )

        await self._check_expansions(segments[0].document_id, glossary)
        await self._add_usage(segments[0].document_id, spent)
        await self._session.commit()

        from_provider = sum(len(group) for _, group in pending)
        flagged = sum(1 for segment in segments if segment.status is SegmentStatus.FLAGGED)

        return TranslationSummary(
            total=len(segments),
            from_memory=from_memory,
            from_provider=from_provider,
            flagged=flagged,
            unique_texts=len(groups),
            provider_calls=len(pending),
            usage=spent,
        )

    async def _call_provider(
        self,
        pending: list[tuple[str, list[Segment]]],
        *,
        glossary: Glossary,
        context: dict[uuid.UUID, Neighbourhood],
        source_language: str,
        target_language: str,
    ) -> tuple[list[tuple[str, str]], Usage]:
        """Перевести то, чего не нашлось в памяти.

        Возвращает пары для памяти и расход: считать его выше по стеку не
        по чему — пачки формируются здесь.
        """
        if not pending:
            return [], Usage()

        batch_size = get_settings().translation_batch_size
        pairs: list[tuple[str, str]] = []
        spent = Usage()

        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]

            requests = [
                TranslationRequest(
                    source_text=group[0].source_text,
                    source_language=source_language,
                    target_language=target_language,
                    terms=glossary.match(group[0].source_text),
                    kind=group[0].kind.value,
                    # Контекст берётся у первого вхождения: у повторяющегося
                    # сегмента соседи разные, а перевод обязан быть один.
                    # Для повтора это и не потеря — предупреждение, которое
                    # повторяется сорок раз, от соседей не зависит.
                    context=context.get(group[0].id, EMPTY_CONTEXT),
                )
                for _, group in chunk
            ]

            batch = await self._provider.translate(requests)
            spent = spent + batch.usage

            if len(batch.texts) != len(requests):
                raise ConflictError(
                    "Провайдер вернул другое число переводов: "
                    f"ожидалось {len(requests)}, получено {len(batch.texts)}"
                )

            for (_, group), answer in zip(chunk, batch.texts, strict=True):
                for segment in group:
                    self._apply(
                        segment, answer, self._provider.name, SegmentStatus.MACHINE, glossary
                    )

                pairs.append((group[0].source_text, answer))

        return pairs, spent

    async def _add_usage(self, document_id: uuid.UUID, spent: Usage) -> None:
        """Прибавить расход запуска к итогу документа.

        Нарастающим итогом, а не заменой: книгу переводят в несколько
        заходов — сначала целиком, потом добавленную главу, — и стоимость
        документа складывается из всех.
        """
        if spent == Usage():
            return

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            return

        document.input_tokens += spent.input_tokens
        document.output_tokens += spent.output_tokens
        document.cached_input_tokens += spent.cached_input_tokens
        document.cache_write_tokens += spent.cache_write_tokens
        document.translated_by = self._provider.name

    def _apply(
        self,
        segment: Segment,
        target_text: str,
        source: str,
        status: SegmentStatus,
        glossary: Glossary,
    ) -> None:
        segment.target_text = target_text
        segment.translation_source = source

        findings = checks.run_checks(
            segment.source_text, target_text, glossary=glossary, kind=segment.kind
        )

        # Помечаем, а не переспрашиваем модель на месте: решение, что делать
        # с находкой — поправить руками или перевести заново, — принимается
        # не здесь.
        segment.status = SegmentStatus.FLAGGED if findings else status
        segment.quality = checks.as_json(findings)
        segment.quality_score = checks.score(findings) if findings else None

    async def _neighbourhood(self, document_id: uuid.UUID) -> dict[uuid.UUID, Neighbourhood]:
        """Собрать окружение каждого сегмента документа.

        Читается весь документ, а не только то, что переводится сейчас:
        соседом непереведённого сегмента может быть давно готовый, и без
        него контекст рвётся ровно на границе прошлого запуска.
        """
        size = get_settings().translation_context_segments

        segments = list(
            await self._session.scalars(
                self.scoped(Segment)
                .where(Segment.document_id == document_id)
                .order_by(Segment.position)
            )
        )

        context: dict[uuid.UUID, Neighbourhood] = {}
        heading: str | None = None

        for index, segment in enumerate(segments):
            context[segment.id] = Neighbourhood(
                before=tuple(item.source_text for item in segments[max(0, index - size) : index]),
                after=tuple(item.source_text for item in segments[index + 1 : index + 1 + size]),
                heading=heading,
            )

            # Заголовок обновляется после того, как записан контекст: для
            # самого заголовка предметную область задаёт предыдущий, а не он
            # сам.
            if segment.kind is SegmentKind.HEADING:
                heading = segment.source_text

        return context

    async def _check_expansions(self, document_id: uuid.UUID, glossary: Glossary) -> None:
        """Проверить, что аббревиатуры раскрыты при первом употреблении.

        Проверка документная, а не посегментная: «первое употребление»
        существует только в масштабе всего документа, и по одному сегменту
        сказать, первый он или сороковой, нельзя.

        Идём по всему документу, а не по переведённому в этот раз: первое
        вхождение могло достаться из памяти ещё в прошлый запуск, и
        требовать раскрытия от сорокового по счёту сегмента было бы ровно
        наоборот.
        """
        expandable = {term.source for term in glossary.terms if term.expand_on_first_use}
        if not expandable:
            return

        segments = list(
            await self._session.scalars(
                self.scoped(Segment)
                .where(Segment.document_id == document_id)
                .order_by(Segment.position)
            )
        )

        seen: set[str] = set()

        for segment in segments:
            if not segment.target_text:
                continue

            for term in glossary.match(segment.source_text):
                if term.source not in expandable or term.source in seen:
                    continue

                seen.add(term.source)
                finding = checks.first_use_finding(term, segment.target_text)

                if finding is not None:
                    self._add_finding(segment, finding)

    @staticmethod
    def _add_finding(segment: Segment, finding: checks.Finding) -> None:
        """Добавить находку к сегменту, не потеряв прежние."""
        previous = [
            checks.Finding(check=str(item["check"]), message=str(item["message"]))
            for item in (segment.quality or {}).get("findings", [])
        ]

        findings = [*previous, finding]

        segment.status = SegmentStatus.FLAGGED
        segment.quality = checks.as_json(findings)
        segment.quality_score = checks.score(findings)
