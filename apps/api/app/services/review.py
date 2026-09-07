"""Редакторский цикл: правка, приёмка и то, что из них следует.

Перевод заканчивается не тогда, когда модель ответила, а тогда, когда
человек его принял. Здесь живёт эта часть работы, и у неё два свойства,
которых нет у машинного перевода.

Первое: **правка человека распространяется на повторы.** Одинаковый
исходник в книге обязан звучать одинаково — ради этого повторы и
переводились один раз. Если редактор поправил одно вхождение, а остальные
сорок остались как были, книга становится несогласованной ровно в том
месте, где согласованность была гарантирована. Поэтому правка расходится по
непринятым повторам того же документа — и только по ним: сегмент, который
человек уже правил или принял, чужой правкой не трогается никогда.

Второе: **правка попадает в память переводов как человеческая** и вытесняет
оттуда машинный вариант. Следующий документ получит уже исправленное, и
редактор не будет править одно и то же во второй раз.

Приёмка от правки отделена намеренно. «Я это поправил» и «я за это отвечаю»
— разные утверждения, и второе нельзя ставить автоматически: сегмент,
исправленный наспех посреди чужой правки, ещё не принят.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select

from app.models.document import Document, DocumentStatus
from app.models.organization import Role
from app.models.project import Project
from app.models.segment import Segment, SegmentStatus
from app.services import checks
from app.services.base import TenantService
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.glossary import Glossary, GlossaryService
from app.services.memory import TranslationMemory, fingerprint

EDITING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER)

HUMAN = "human"

# Статусы, которые правка вправе переписать у повторов. Отредактированное и
# принятое сюда не входит: у них за спиной решение человека, и чужая правка
# соседнего вхождения его не отменяет.
OVERWRITABLE = (
    SegmentStatus.NEW,
    SegmentStatus.MACHINE,
    SegmentStatus.MEMORY,
    SegmentStatus.FLAGGED,
)


@dataclass(slots=True)
class EditResult:
    segment: Segment
    # Сколько повторов того же текста подтянулось за правкой. Число нужно
    # редактору: он поправил одну строку, а изменилось сорок, и знать об
    # этом он должен до того, как увидит это в готовой книге.
    propagated: int


@dataclass(slots=True)
class Progress:
    """Состояние документа для полосы выполнения и списка задач."""

    total: int
    # Есть перевод — любой: машинный, из памяти, правленый, принятый.
    translated: int
    # Ждут человека: проверки что-то нашли.
    flagged: int
    edited: int
    approved: int
    # Ещё не переводились.
    untouched: int

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.approved == self.total


class ReviewService(TenantService):
    async def edit(self, segment_id: uuid.UUID, target_text: str) -> EditResult:
        """Записать правку редактора.

        Пустой текст не принимается: «стереть перевод» — это не правка, а
        возврат к непереведённому состоянию, и делается он повторным
        переводом. Молча принятая пустая строка выглядела бы как принятая
        работа.
        """
        self._context.require(*EDITING_ROLES)

        target_text = target_text.strip()
        if not target_text:
            raise InvalidInputError("Перевод не может быть пустым")

        segment = await self._segment(segment_id)
        document, project = await self._document_and_project(segment.document_id)

        glossary = await GlossaryService(self._session, self._context).load(
            project_id=document.project_id,
            source_language=project.source_language,
            target_language=project.target_language,
        )

        self._write(segment, target_text, glossary, SegmentStatus.EDITED)

        propagated = await self._propagate(segment, target_text, glossary)

        # Правка человека вытесняет машинный вариант в памяти: следующий
        # документ получит уже исправленное.
        await TranslationMemory(self._session, self._context).remember(
            [(segment.source_text, target_text)],
            source_language=project.source_language,
            target_language=project.target_language,
            origin=HUMAN,
        )

        await self._session.commit()
        await self._session.refresh(segment)

        return EditResult(segment=segment, propagated=propagated)

    async def approve(self, segment_id: uuid.UUID) -> Segment:
        """Принять сегмент.

        Принять сегмент с находками можно: проверка машинная и ошибается,
        а решение за человеком. Находки при этом не стираются — остаётся
        видно, что именно было замечено и всё-таки принято.
        """
        self._context.require(*EDITING_ROLES)

        segment = await self._segment(segment_id)

        if not (segment.target_text or "").strip():
            raise ConflictError("Нечего принимать: сегмент не переведён")

        segment.status = SegmentStatus.APPROVED

        await self._session.commit()
        await self._finish_document(segment.document_id)
        await self._session.refresh(segment)

        return segment

    async def reopen(self, segment_id: uuid.UUID) -> Segment:
        """Вернуть принятый сегмент в работу.

        Статус зависит от того, что нашли проверки: сегмент с находками
        снова помечен, чистый — возвращается к правленому. Ставить всем
        подряд EDITED значило бы прятать находку, ради которой сегмент и
        открыли заново.
        """
        self._context.require(*EDITING_ROLES)

        segment = await self._segment(segment_id)
        segment.status = SegmentStatus.FLAGGED if segment.quality else SegmentStatus.EDITED

        await self._session.commit()

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == segment.document_id)
        )
        if document is not None and document.status is DocumentStatus.DONE:
            document.status = DocumentStatus.REVIEW
            await self._session.commit()

        await self._session.refresh(segment)

        return segment

    async def approve_clean(self, document_id: uuid.UUID) -> int:
        """Принять всё, к чему у проверок нет претензий.

        Без этого приёмка книги — три тысячи нажатий, и делать её никто не
        станет. Помеченное проверками остаётся редактору: смысл разделения в
        том, чтобы его внимание доставалось спорному, а не всему подряд.
        """
        self._context.require(*EDITING_ROLES)

        await self._document_and_project(document_id)

        segments = list(
            await self._session.scalars(
                self.scoped(Segment).where(
                    Segment.document_id == document_id,
                    Segment.quality.is_(None),
                    Segment.target_text.is_not(None),
                    Segment.status.in_(
                        [SegmentStatus.MACHINE, SegmentStatus.MEMORY, SegmentStatus.EDITED]
                    ),
                )
            )
        )

        for segment in segments:
            segment.status = SegmentStatus.APPROVED

        await self._session.commit()
        await self._finish_document(document_id)

        return len(segments)

    async def progress(self, document_id: uuid.UUID) -> Progress:
        """Сколько сделано — одним запросом, а не выгрузкой всех сегментов."""
        await self._document_and_project(document_id)

        rows = await self._session.execute(
            select(Segment.status, func.count())
            .where(
                Segment.organization_id == self.organization_id,
                Segment.document_id == document_id,
            )
            .group_by(Segment.status)
        )

        counts = {status: int(count) for status, count in rows.all()}
        total = sum(counts.values())
        untouched = counts.get(SegmentStatus.NEW, 0)

        return Progress(
            total=total,
            translated=total - untouched,
            flagged=counts.get(SegmentStatus.FLAGGED, 0),
            edited=counts.get(SegmentStatus.EDITED, 0),
            approved=counts.get(SegmentStatus.APPROVED, 0),
            untouched=untouched,
        )

    def _write(
        self,
        segment: Segment,
        target_text: str,
        glossary: Glossary,
        status: SegmentStatus,
    ) -> None:
        """Записать перевод и перепроверить его.

        Проверки прогоняются заново: правка меняет и текст, и находки, а
        оставшаяся от машинного перевода отметка «не употреблён термин»
        держала бы сегмент помеченным после того, как его исправили.
        """
        segment.target_text = target_text
        segment.translation_source = HUMAN

        findings = checks.run_checks(
            segment.source_text, target_text, glossary=glossary, kind=segment.kind
        )

        segment.quality = checks.as_json(findings)
        segment.quality_score = checks.score(findings) if findings else None
        segment.status = SegmentStatus.FLAGGED if findings else status

    async def _propagate(self, edited: Segment, target_text: str, glossary: Glossary) -> int:
        """Разнести правку по непринятым повторам того же документа."""
        digest = fingerprint(edited.source_text)

        candidates = await self._session.scalars(
            self.scoped(Segment).where(
                Segment.document_id == edited.document_id,
                Segment.id != edited.id,
                Segment.status.in_(list(OVERWRITABLE)),
            )
        )

        touched = 0
        for segment in candidates:
            if fingerprint(segment.source_text) != digest:
                continue

            self._write(segment, target_text, glossary, SegmentStatus.EDITED)
            touched += 1

        return touched

    async def _finish_document(self, document_id: uuid.UUID) -> None:
        """Перевести документ в «готов», когда принят последний сегмент."""
        remaining = await self._session.scalar(
            select(func.count())
            .select_from(Segment)
            .where(
                Segment.organization_id == self.organization_id,
                Segment.document_id == document_id,
                Segment.status != SegmentStatus.APPROVED,
            )
        )

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            return

        if int(remaining or 0) == 0 and document.status is not DocumentStatus.DONE:
            document.status = DocumentStatus.DONE
            await self._session.commit()

    async def _segment(self, segment_id: uuid.UUID) -> Segment:
        segment = await self._session.scalar(self.scoped(Segment).where(Segment.id == segment_id))
        if segment is None:
            raise NotFoundError("Сегмент не найден")

        return segment

    async def _document_and_project(self, document_id: uuid.UUID) -> tuple[Document, Project]:
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

        return document, project
