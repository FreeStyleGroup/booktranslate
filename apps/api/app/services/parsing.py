"""Разбор документа на сегменты.

Связывает три части, каждая из которых сама по себе ничего не знает про
остальные: хранилище отдаёт файл, разборщик формата превращает его в блоки,
нарезка делит блоки на сегменты. Здесь же живут статусы документа — единственное
место, где они меняются по ходу разбора.

Разбор идёт синхронно, в рамках запроса. Очередь задач тут будет нужна, но
позже и по измеримой причине: пока неизвестно, сколько занимает книга на
тысячу страниц, выбирать между потоком, воркером и внешним сервисом не на чем.
Ограничение осознанное и записано в журнале.
"""

import asyncio
import logging
import os
import tempfile
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.organization import Role
from app.models.segment import Segment, SegmentStatus
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.documents import DocumentService
from app.services.errors import ConflictError, UnsupportedFormatError
from app.services.parsers import DocumentParser, ParsedBlock, ParsingError, parser_for
from app.services.segmentation import split_block
from app.services.storage import ObjectStorage
from app.services.translation import is_stale

logger = logging.getLogger(__name__)

# Разбор — обработка чужого материала, а не правка: наблюдателю он не нужен,
# остальным ролям нужен. Набор совпадает с загрузкой намеренно: тот, кто
# принёс файл, должен уметь его и разобрать, иначе работа встаёт до менеджера.
PARSING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

# Сегменты пишутся пачками: одна вставка на тысячу строк вместо тысячи
# вставок. Размер подобран так, чтобы запрос оставался читаемым для базы и
# не съедал память на книге в сотню тысяч сегментов.
INSERT_BATCH = 500


class ParsingService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def parse(self, document_id: uuid.UUID, *, force: bool = False) -> Document:
        """Разобрать документ на сегменты.

        Повторный вызов на разобранном документе отклоняется: сегменты уже
        могли быть переведены и отредактированы, и молча заменить их значит
        потерять работу человека. Осознанный повтор — `force=True`.

        Документ, застрявший в «разбирается», тоже берётся только с
        `force=True` — и только если разбор молчит дольше порога: отметку
        оставил убитый процесс, а не идущий разбор. Сегменты пишутся одной
        транзакцией, поэтому у такого документа либо прежний полный набор,
        либо ничего — терять нечего.
        """
        self._context.require(*PARSING_ROLES)

        documents = DocumentService(self._session, self._context, self._storage)
        document = await documents.get(document_id)

        if document.status == DocumentStatus.PARSING:
            settings = get_settings()
            stale = is_stale(
                document.updated_at,
                now=datetime.now(UTC),
                threshold=timedelta(minutes=settings.translation_stale_minutes),
            )

            if not (force and stale):
                hint = (
                    f" Разбор молчит дольше {settings.translation_stale_minutes} мин: "
                    "если он прерван, повторите с force=true."
                    if stale
                    else ""
                )
                raise ConflictError("Документ уже разбирается." + hint)

            logger.warning(
                "Документ %s взят на разбор повторно: прежний разбор молчал с %s",
                document.id,
                document.updated_at.isoformat(),
            )

        if document.status != DocumentStatus.UPLOADED and not force:
            raise ConflictError(
                "Документ уже разобран. Повторный разбор удалит существующие "
                "сегменты вместе с переводом — передайте force=true, если это нужно"
            )

        parser = parser_for(document.source_format)
        if parser is None:
            raise UnsupportedFormatError(
                f"Разбор формата {document.source_format.value} пока не поддерживается"
            )

        document.status = DocumentStatus.PARSING
        document.error = None
        await self._session.commit()

        try:
            blocks = await self._read_blocks(document, parser)
            count = await self._replace_segments(document, blocks)
        except (ParsingError, OSError) as error:
            # Причина остаётся в записи: без неё пользователь видит «сломалось»
            # и не знает, чинить ему файл или писать в поддержку.
            document.status = DocumentStatus.FAILED
            document.error = str(error)[:2000]
            await self._session.commit()
            await self._session.refresh(document)

            return document

        document.status = DocumentStatus.PARSED
        document.error = None if count else "Документ разобран, но текста в нём не нашлось"
        await self._session.commit()
        await self._session.refresh(document)

        return document

    async def list_segments(
        self,
        document_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
        statuses: Sequence[SegmentStatus] | None = None,
        worst_first: bool = False,
    ) -> list[Segment]:
        """Сегменты документа — целиком или отобранные для правки.

        `worst_first` меняет порядок с документного на «сначала спорное»:
        редактор разбирает не книгу подряд, а список замечаний, и начинать
        должен с худшего. Сегменты без находок в этом порядке идут
        последними — оценки у них нет вовсе.
        """
        # Документ запрашивается ради проверки принадлежности: пустой список
        # на чужой документ выглядел бы как «сегментов нет».
        await DocumentService(self._session, self._context, self._storage).get(document_id)

        query = self._filtered(
            self.scoped(Segment).where(Segment.document_id == document_id), statuses
        )

        if worst_first:
            # NULLS LAST задано явно: в Postgres при сортировке по
            # возрастанию NULL и так уходят в конец, но порядок здесь несёт
            # смысл, и полагаться на умолчание базы в таком месте не стоит.
            query = query.order_by(Segment.quality_score.asc().nulls_last(), Segment.position)
        else:
            query = query.order_by(Segment.position)

        return list(await self._session.scalars(query.limit(limit).offset(offset)))

    async def count_segments(
        self, document_id: uuid.UUID, *, statuses: Sequence[SegmentStatus] | None = None
    ) -> int:
        query = (
            select(func.count())
            .select_from(Segment)
            .where(
                Segment.organization_id == self.organization_id,
                Segment.document_id == document_id,
            )
        )

        return int(await self._session.scalar(self._filtered(query, statuses)) or 0)

    @staticmethod
    def _filtered(query: Any, statuses: Sequence[SegmentStatus] | None) -> Any:
        """Отбор по статусу — общий для страницы и для счётчика.

        Общий намеренно: разойдясь, они дадут страницу из десяти строк при
        заявленной тысяче, и полоса прокрутки станет врать.
        """
        if not statuses:
            return query

        return query.where(Segment.status.in_(list(statuses)))

    async def _read_blocks(self, document: Document, parser: DocumentParser) -> list[ParsedBlock]:
        """Забрать файл из хранилища во временный и разобрать его.

        Разборщики работают с файлом на диске, а не с потоком: и python-docx,
        и zipfile требуют возможности читать с произвольного места, которой у
        потока нет. Временный файл удаляется в любом случае.
        """
        descriptor, name = tempfile.mkstemp(prefix="booktranslate-parse-")
        path = Path(name)

        try:
            with os.fdopen(descriptor, "wb") as handle:
                async for chunk in self._storage.stream(document.storage_key):
                    await asyncio.to_thread(handle.write, chunk)

            # Разбор — блокирующая работа с диском и разметкой. В потоке
            # событий она остановила бы обслуживание остальных запросов.
            return await asyncio.to_thread(lambda: list(parser.parse(path)))
        finally:
            path.unlink(missing_ok=True)

    async def _replace_segments(self, document: Document, blocks: list[ParsedBlock]) -> int:
        """Записать сегменты, заменив прежние.

        Удаление и вставка идут одной транзакцией: документ не должен
        оказаться наполовину старым, наполовину новым, если разбор прервётся
        на середине.
        """
        settings = get_settings()

        await self._session.execute(
            delete(Segment).where(
                Segment.organization_id == self.organization_id,
                Segment.document_id == document.id,
            )
        )

        position = 0
        batch: list[Segment] = []

        for block in blocks:
            texts = split_block(
                block.text,
                target_chars=settings.segment_target_chars,
                hard_limit_chars=settings.segment_hard_limit_chars,
            )

            for part, text in enumerate(texts):
                location = dict(block.location)
                # Номер части нужен только там, где блок действительно резали:
                # иначе он загромождал бы каждую запись нулём.
                if len(texts) > 1:
                    location["part"] = part

                batch.append(
                    Segment(
                        organization_id=self.organization_id,
                        document_id=document.id,
                        position=position,
                        kind=block.kind,
                        status=SegmentStatus.NEW,
                        source_text=text,
                        source_location=location or None,
                    )
                )
                position += 1

            if len(batch) >= INSERT_BATCH:
                self._session.add_all(batch)
                await self._session.flush()
                batch = []

        if batch:
            self._session.add_all(batch)
            await self._session.flush()

        return position
