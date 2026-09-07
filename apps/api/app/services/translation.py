"""Перевод сегментов.

Порядок шагов выбран так, чтобы платить как можно меньше, и он важнее самого
вызова модели:

1. **Дедупликация внутри документа.** «Внимание! Перед обслуживанием
   отключите питание.» встречается в руководстве десятки раз. Переводится
   один раз.
2. **Память переводов.** Всё, что уже переводилось для этой организации и
   этой языковой пары, берётся готовым. Точное совпадение стоит ноль, а не
   «дёшево»; на второй книге серии так закрывается заметная часть объёма.
3. **Модель — только на остаток.** В запрос уходят термины глоссария,
   встретившиеся именно в этом сегменте.
4. **Проверка глоссария на выходе.** Сегмент, где обязательный термин не
   употреблён, помечается — дальше его смотрит человек либо (когда появится
   маршрутизация) модель подороже.

Результат перевода возвращается в память, поэтому следующий документ
обходится дешевле предыдущего.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.organization import Role
from app.models.project import Project
from app.models.segment import Segment, SegmentStatus
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import ConflictError, NotFoundError
from app.services.glossary import Glossary, GlossaryService
from app.services.memory import TranslationMemory, fingerprint
from app.services.providers import TranslationProvider, TranslationRequest

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

    @property
    def saved_calls(self) -> int:
        """Сколько обращений к модели не понадобилось.

        Считается от общего числа сегментов: повторы внутри документа и
        совпадения с памятью — это ровно то, за что не заплачено.
        """
        return self.total - self.from_provider


class TranslationService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, provider: TranslationProvider
    ) -> None:
        super().__init__(session, context)
        self._provider = provider

    async def translate(self, document_id: uuid.UUID, *, force: bool = False) -> TranslationSummary:
        self._context.require(*TRANSLATING_ROLES)

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        if document.status in (DocumentStatus.UPLOADED, DocumentStatus.PARSING):
            raise ConflictError("Документ ещё не разобран на сегменты")

        project = await self._session.scalar(
            self.scoped(Project).where(Project.id == document.project_id)
        )
        if project is None:
            raise NotFoundError("Проект не найден")

        segments = await self._segments(document_id, force=force)
        if not segments:
            return TranslationSummary(0, 0, 0, 0, 0)

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

        translated = await self._call_provider(
            pending,
            glossary=glossary,
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
        await self._session.commit()

        from_provider = sum(len(group) for _, group in pending)
        flagged = sum(1 for segment in segments if segment.status is SegmentStatus.FLAGGED)

        return TranslationSummary(
            total=len(segments),
            from_memory=from_memory,
            from_provider=from_provider,
            flagged=flagged,
            unique_texts=len(groups),
        )

    async def _call_provider(
        self,
        pending: list[tuple[str, list[Segment]]],
        *,
        glossary: Glossary,
        source_language: str,
        target_language: str,
    ) -> list[tuple[str, str]]:
        """Перевести то, чего не нашлось в памяти. Возвращает пары для памяти."""
        if not pending:
            return []

        batch_size = get_settings().translation_batch_size
        pairs: list[tuple[str, str]] = []

        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]

            requests = [
                TranslationRequest(
                    source_text=group[0].source_text,
                    source_language=source_language,
                    target_language=target_language,
                    terms=glossary.match(group[0].source_text),
                    kind=group[0].kind.value,
                )
                for _, group in chunk
            ]

            answers = await self._provider.translate(requests)
            if len(answers) != len(requests):
                raise ConflictError(
                    "Провайдер вернул другое число переводов: "
                    f"ожидалось {len(requests)}, получено {len(answers)}"
                )

            for (_, group), answer in zip(chunk, answers, strict=True):
                for segment in group:
                    self._apply(
                        segment, answer, self._provider.name, SegmentStatus.MACHINE, glossary
                    )

                pairs.append((group[0].source_text, answer))

        return pairs

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

        missing = glossary.missing_in(segment.source_text, target_text)

        if missing:
            # Помечаем, а не переспрашиваем модель на месте: решение, что
            # делать с расхождением — показать человеку или отправить в
            # модель подороже, — принимается не здесь.
            segment.status = SegmentStatus.FLAGGED
            segment.quality = {
                "glossary": [{"source": term.source, "expected": term.target} for term in missing]
            }
        else:
            segment.status = status
            segment.quality = None
