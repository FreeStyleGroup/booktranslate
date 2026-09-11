"""Паспорт документа: что это за книга и во что обойдётся её перевод.

Отвечает на вопросы, которые задают до того, как платить: сколько в файле
текста, из чего он состоит, сколько в нём повторов, что из этого уже
закрыто памятью переводов и сколько остаётся оплачивать.

Считается по запросу, а не хранится в документе. Причина та же, по которой
готовность не лежит колонкой: числа меняются после каждой правки и каждого
прогона, и сохранённые однажды они разойдутся с действительностью — молча
и незаметно, потому что выглядеть будут правдоподобно.

Повторы и совпадения с памятью считаются только среди непереведённого:
смете интересно то, за что ещё предстоит заплатить, а у переведённых
сегментов счёт уже выставлен и лежит в токенах документа.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.models.document import Document
from app.models.project import Project
from app.models.segment import Segment, SegmentStatus
from app.services.base import TenantService
from app.services.errors import NotFoundError
from app.services.memory import TranslationMemory, fingerprint
from app.services.pricing import Forecast, forecast

# Сколько строк читать из базы за раз при обходе непереведённых сегментов.
# Обход нужен целиком — отпечаток считается в Python, тем же кодом, что и
# при переводе, — но держать в памяти всю книгу разом незачем.
READ_BATCH = 1000


@dataclass(slots=True)
class DocumentProfile:
    """Состав документа и смета на его перевод."""

    segments: int = 0
    characters: int = 0
    words: int = 0
    longest_segment_chars: int = 0

    # Из чего книга состоит: заголовки, абзацы, ячейки таблиц,
    # предупреждения. По этому раскладу видно, что за файл принесли —
    # связный текст, таблицу спецификаций или оглавление.
    by_kind: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)

    untranslated: int = 0
    # Сколько среди непереведённых различных текстов и сколько повторов.
    # Повтор переводится один раз — и ради единообразия, и ради денег.
    unique_untranslated: int = 0
    repeated: int = 0
    # Из различных текстов — те, что память переводов закрывает уже сейчас.
    memory_matches: int = 0

    # За что предстоит заплатить: различные тексты, которых нет в памяти.
    billable_texts: int = 0
    billable_characters: int = 0

    estimate: Forecast | None = None


class ProfilingService(TenantService):
    async def build(
        self, document_id: uuid.UUID, *, model: str, context_segments: int
    ) -> DocumentProfile:
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

        profile = await self._volume(document.id)

        profile.by_kind = await self._grouped(document.id, Segment.kind)
        profile.by_status = await self._grouped(document.id, Segment.status)

        await self._billable(
            document.id,
            profile,
            source_language=project.source_language,
            target_language=project.target_language,
        )

        if profile.billable_characters > 0:
            profile.estimate = forecast(
                model,
                characters=profile.billable_characters,
                context_segments=context_segments,
            )

        return profile

    async def _volume(self, document_id: uuid.UUID) -> DocumentProfile:
        """Объём текста одним запросом.

        Слова считает база: вытащить ради этого числа всю книгу на сторону
        приложения — это десятки мегабайт по сети на каждый показ карточки.
        """
        length = func.length(Segment.source_text)
        # array_length возвращает NULL на пустом массиве — у сегмента без
        # текста это ноль слов, а не отсутствие ответа.
        words = func.coalesce(
            func.array_length(
                func.regexp_split_to_array(func.btrim(Segment.source_text), r"\s+"), 1
            ),
            0,
        )

        row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(length), 0),
                    func.coalesce(func.sum(words), 0),
                    func.coalesce(func.max(length), 0),
                ).where(*self._of(document_id))
            )
        ).one()

        return DocumentProfile(
            segments=int(row[0]),
            characters=int(row[1]),
            words=int(row[2]),
            longest_segment_chars=int(row[3]),
        )

    async def _grouped(
        self, document_id: uuid.UUID, column: InstrumentedAttribute[Any]
    ) -> dict[str, int]:
        """Сколько сегментов в каждом значении перечисления.

        Наружу уходят строковые значения: витрина рисует по ним подписи, и
        переводить их здесь значило бы вшить язык интерфейса в данные.
        """
        rows = await self._session.execute(
            select(column, func.count())
            .select_from(Segment)
            .where(*self._of(document_id))
            .group_by(column)
        )

        return {value.value: int(amount) for value, amount in rows.all()}

    async def _billable(
        self,
        document_id: uuid.UUID,
        profile: DocumentProfile,
        *,
        source_language: str,
        target_language: str,
    ) -> None:
        """Пересчитать непереведённое в то, за что придётся платить.

        Отпечаток считается тем же `fingerprint`, что и при переводе:
        разойдись они — смета обещала бы экономию на повторах, которой
        перевод потом не найдёт.
        """
        chars_by_text: dict[str, int] = {}
        total = 0

        stream = await self._session.stream_scalars(
            select(Segment.source_text)
            .where(*self._of(document_id), Segment.status == SegmentStatus.NEW)
            .execution_options(yield_per=READ_BATCH)
        )

        async for text in stream:
            total += 1
            chars_by_text.setdefault(fingerprint(text), len(text))

        profile.untranslated = total
        profile.unique_untranslated = len(chars_by_text)
        profile.repeated = total - len(chars_by_text)

        if not chars_by_text:
            return

        known = await TranslationMemory(self._session, self._context).known(
            set(chars_by_text),
            source_language=source_language,
            target_language=target_language,
        )

        profile.memory_matches = len(known)
        profile.billable_texts = len(chars_by_text) - len(known)
        profile.billable_characters = sum(
            chars for digest, chars in chars_by_text.items() if digest not in known
        )

    def _of(self, document_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
        """Условия отбора сегментов документа — с организацией.

        Одним местом, потому что забытое условие по организации здесь
        показало бы клиенту объём чужой книги.
        """
        return (
            Segment.organization_id == self.organization_id,
            Segment.document_id == document_id,
        )
