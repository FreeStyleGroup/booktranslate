"""Утверждение и правка границ глав.

Каждое действие здесь — решение, и каждое оставляет запись в журнале с
автором: процесс требует, чтобы по готовой главе было видно, кто и когда
принял её границы и откуда они взялись.

Правила, которые держит этот модуль:

* код главы (`CH03`) выдаётся при первом утверждении и больше не
  меняется; утверждают по порядку книги, поэтому код совпадает с местом
  главы на момент утверждения;
* любое изменение границ утверждённой главы возвращает её в черновик и
  поднимает `boundary_version` — по версии позже узнают, какие проверки
  сделаны по прежним границам;
* делят и сливают главы по границам разделов: делить посреди раздела —
  значит оторвать подзаголовок от его текста.

Все действия берут строку книги под блокировку: они переписывают места
соседних глав, и два одновременных действия сдвинули бы их дважды.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from app.models.chapter import BoundaryStatus, Chapter, ChapterOrigin
from app.models.coding import CodeKind
from app.models.document import Document, SourceRole
from app.models.master import ChapterMaster
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.books import MANAGING_ROLES, BookService
from app.services.coding import CodeAllocator
from app.services.errors import ConflictError, InvalidInputError, NotFoundError

# Названия длиннее колонки не лягут; пробелы по краям — опечатка.
TITLE_MAX = 500


@dataclass(frozen=True, slots=True)
class BookStructure:
    """Главы книги и то, по какому файлу они размечены.

    `source_is_primary` ложно, когда основной источник сменили после
    разметки: границы заданы номерами блоков прежнего файла и к новому не
    подходят. Об этом надо сказать, а не показывать главы как ни в чём не
    бывало.
    """

    chapters: list[Chapter]
    source: Document | None
    source_is_primary: bool
    # Заново предлагать можно, пока ни одна глава не получала кода.
    can_propose: bool


class ChapterApprovalService(TenantService):
    async def structure(self, book_id: uuid.UUID) -> BookStructure:
        book = await BookService(self._session, self._context).get(book_id)
        chapters = await self._chapters(book.id)

        source = (
            await self._session.scalar(
                self.scoped(Document).where(Document.id == chapters[0].source_document_id)
            )
            if chapters
            else None
        )

        return BookStructure(
            chapters=chapters,
            source=source,
            source_is_primary=source is not None
            and source.book_id == book.id
            and source.source_role is SourceRole.PRIMARY_TEXT,
            can_propose=all(chapter.number is None for chapter in chapters),
        )

    async def approve(self, chapter_id: uuid.UUID) -> Chapter:
        """Утвердить границы главы.

        Главы выше обязаны быть утверждены: код выдаётся по порядку книги,
        и утверждение вразнобой дало бы пятой главе код `CH01`.
        """
        self._context.require(*MANAGING_ROLES)

        chapter = await self._locked(chapter_id)
        await self._approve(chapter, await self._chapters(chapter.book_id))
        await self._session.commit()
        await self._session.refresh(chapter)

        return chapter

    async def approve_all(self, book_id: uuid.UUID) -> list[Chapter]:
        """Утвердить все черновики книги — по порядку, сверху вниз.

        Решение по каждой главе записывается отдельно: «утвердил всё разом»
        в журнале не отличить от «утвердил то, что было на экране».
        """
        self._context.require(*MANAGING_ROLES)

        book = await BookService(self._session, self._context).lock(book_id)
        chapters = await self._chapters(book.id)

        if not chapters:
            raise ConflictError("У книги ещё нет глав — сначала предложите их")

        for chapter in chapters:
            if chapter.boundary_status is BoundaryStatus.DRAFT:
                await self._approve(chapter, chapters)

        await self._session.commit()

        return await self._chapters(book.id)

    async def split(self, chapter_id: uuid.UUID, *, at: int) -> list[Chapter]:
        """Разделить главу по началу раздела `at`.

        Первая часть остаётся той же главой — с её кодом, если он был;
        вторая — новый черновик, код получит при утверждении. Обе
        возвращаются в черновик: границы изменились, и прежнее решение
        к ним больше не относится.
        """
        self._context.require(*MANAGING_ROLES)

        chapter = await self._locked(chapter_id)
        await self._require_no_master(chapter)
        sections: list[dict[str, Any]] = chapter.sections
        starts = [section["start"] for section in sections]

        if at not in starts[1:]:
            raise InvalidInputError(
                "Делить главу можно только по началу одного из её разделов, кроме первого"
            )

        cut = starts.index(at)
        head, tail = sections[:cut], sections[cut:]

        await self._session.execute(
            update(Chapter)
            .where(Chapter.book_id == chapter.book_id, Chapter.ordinal > chapter.ordinal)
            .values(ordinal=Chapter.ordinal + 1)
        )

        part = Chapter(
            organization_id=self.organization_id,
            book_id=chapter.book_id,
            source_document_id=chapter.source_document_id,
            ordinal=chapter.ordinal + 1,
            title=tail[0]["title"],
            source_start=at,
            source_end=chapter.source_end,
            parser_version=chapter.parser_version,
            locator=tail[0]["locator"],
            sections=tail,
            origin=ChapterOrigin.MANUAL,
            boundary_status=BoundaryStatus.DRAFT,
            boundary_version=1,
        )
        self._session.add(part)

        chapter.sections = head
        chapter.source_end = at
        self._reopen(chapter)

        await self._session.flush()

        self._audit().record(
            kind="chapter.split",
            subject_type="chapter",
            subject_id=chapter.id,
            payload={
                "book_id": str(chapter.book_id),
                "code": chapter.code,
                "at_block": at,
                "new_chapter_id": str(part.id),
                "boundary_version": chapter.boundary_version,
            },
        )

        await self._session.commit()

        return await self._chapters(chapter.book_id)

    async def merge_next(self, chapter_id: uuid.UUID) -> list[Chapter]:
        """Присоединить к главе следующую за ней.

        Остаётся верхняя глава — с её кодом. Код нижней, если он был,
        выводится из употребления навсегда: счётчик его второй главе не
        выдаст, и ссылки на него в журнале останутся однозначными.
        """
        self._context.require(*MANAGING_ROLES)

        chapter = await self._locked(chapter_id)
        following = await self._session.scalar(
            self.scoped(Chapter).where(
                Chapter.book_id == chapter.book_id, Chapter.ordinal == chapter.ordinal + 1
            )
        )

        if following is None:
            raise ConflictError("Это последняя глава книги — присоединять к ней нечего")

        await self._require_no_master(chapter)
        await self._require_no_master(following)

        if following.source_document_id != chapter.source_document_id:
            # Номера блоков двух разных файлов в одну последовательность не
            # складываются: глава с такими границами ничего бы не значила.
            raise ConflictError("Главы размечены по разным файлам — объединить их нельзя")

        retired = following.code

        # Глава без названия берёт название присоединённой: так обложка,
        # слитая с титулом, получает название книги, а не остаётся «без
        # названия» с названием внутри. Своё название глава не теряет.
        if chapter.title is None:
            chapter.title = following.title

        chapter.sections = [*chapter.sections, *following.sections]
        chapter.source_end = following.source_end
        self._reopen(chapter)

        await self._session.delete(following)
        await self._session.flush()

        await self._session.execute(
            update(Chapter)
            .where(Chapter.book_id == chapter.book_id, Chapter.ordinal > chapter.ordinal + 1)
            .values(ordinal=Chapter.ordinal - 1)
        )

        self._audit().record(
            kind="chapter.merged",
            subject_type="chapter",
            subject_id=chapter.id,
            payload={
                "book_id": str(chapter.book_id),
                "code": chapter.code,
                "absorbed_chapter_id": str(following.id),
                "retired_code": retired,
                "boundary_version": chapter.boundary_version,
            },
        )

        await self._session.commit()

        return await self._chapters(chapter.book_id)

    async def rename(self, chapter_id: uuid.UUID, title: str) -> Chapter:
        """Назвать главу.

        Название — не граница: от него не зависит, какие блоки входят в
        главу, поэтому утверждённая глава утверждённой и остаётся. Решение
        всё равно записывается: название уходит в оглавление выпуска.
        """
        self._context.require(*MANAGING_ROLES)

        clean = " ".join(title.split())

        if not clean:
            raise InvalidInputError("Название главы не может быть пустым")

        if len(clean) > TITLE_MAX:
            raise InvalidInputError(f"Название главы — не длиннее {TITLE_MAX} знаков")

        chapter = await self._locked(chapter_id)
        previous = chapter.title
        chapter.title = clean

        self._audit().record(
            kind="chapter.renamed",
            subject_type="chapter",
            subject_id=chapter.id,
            payload={"book_id": str(chapter.book_id), "title": clean, "previous_title": previous},
        )

        await self._session.commit()
        await self._session.refresh(chapter)

        return chapter

    async def require_approved(self, chapter_id: uuid.UUID) -> Chapter:
        """Глава с утверждёнными границами — или отказ.

        Сюда приходит извлечение мастера: без утверждённых границ оно не
        начинается, иначе мастер был бы извлечён из того, о чём ещё никто
        не договорился.
        """
        chapter = await self._chapter(chapter_id)

        if chapter.boundary_status is not BoundaryStatus.APPROVED:
            raise ConflictError("Границы главы не утверждены")

        return chapter

    async def _approve(self, chapter: Chapter, chapters: list[Chapter]) -> None:
        if chapter.boundary_status is BoundaryStatus.APPROVED:
            return

        pending = [
            other
            for other in chapters
            if other.ordinal < chapter.ordinal and other.boundary_status is BoundaryStatus.DRAFT
        ]
        if pending:
            raise ConflictError("Сначала утвердите главы выше: код главы выдаётся по порядку книги")

        if chapter.number is None:
            chapter.number = await CodeAllocator(self._session, self._context).next(
                CodeKind.CHAPTER, chapter.book_id
            )

        chapter.boundary_status = BoundaryStatus.APPROVED
        chapter.approved_by_id = self._context.user.id
        chapter.approved_at = datetime.now(UTC)

        self._audit().record(
            kind="chapter.approved",
            subject_type="chapter",
            subject_id=chapter.id,
            payload={
                "book_id": str(chapter.book_id),
                "code": chapter.code,
                "boundary_version": chapter.boundary_version,
                "source_start": chapter.source_start,
                "source_end": chapter.source_end,
                # Кто принял решение: человек на экране или сервис по правилу
                # профиля. Сейчас решает только человек; автоматический
                # режим будет писать сюда своё — и в тот же журнал.
                "decided_by": "user",
            },
        )

    async def _require_no_master(self, chapter: Chapter) -> None:
        """У главы ещё нет мастера — значит, её блоки ещё без кодов.

        После извлечения у блоков коды вида `CH03-B0042`: в них код главы.
        Перенеси разделение или слияние блок в другую главу — и его
        постоянный код сменился бы, а на него уже могли сослаться. Поэтому
        границы главы с мастером не двигаются.
        """
        extracted = await self._session.scalar(
            self.scoped(ChapterMaster).where(ChapterMaster.chapter_id == chapter.id).limit(1)
        )

        if extracted is not None:
            raise ConflictError(
                f"У главы {chapter.code or chapter.ordinal} уже извлечён мастер: её блоки получили "
                "коды с кодом главы, и перенос блоков между главами сменил бы их"
            )

    @staticmethod
    def _reopen(chapter: Chapter) -> None:
        """Границы изменились — прежнее утверждение к ним не относится."""
        if chapter.boundary_status is BoundaryStatus.APPROVED:
            chapter.boundary_version += 1

        chapter.boundary_status = BoundaryStatus.DRAFT
        chapter.origin = ChapterOrigin.MANUAL

    async def _locked(self, chapter_id: uuid.UUID) -> Chapter:
        """Глава — после того, как её книга взята под блокировку."""
        chapter = await self._chapter(chapter_id)
        await BookService(self._session, self._context).lock(chapter.book_id)
        # Повторное чтение: пока ждали блокировку, главу могли изменить.
        await self._session.refresh(chapter)

        return chapter

    async def _chapter(self, chapter_id: uuid.UUID) -> Chapter:
        chapter = await self._session.scalar(self.scoped(Chapter).where(Chapter.id == chapter_id))

        if chapter is None:
            raise NotFoundError("Глава не найдена")

        return chapter

    async def _chapters(self, book_id: uuid.UUID) -> list[Chapter]:
        """Главы книги по порядку — как они лежат в базе, а не в памяти.

        После разделения и объединения места соседних глав переписаны
        одним запросом, а сессия не сбрасывает загруженные объекты при
        фиксации. `populate_existing` перечитывает их из базы: список
        с местами из памяти показал бы две главы на одном месте.
        """
        return list(
            await self._session.scalars(
                self.scoped(Chapter)
                .where(Chapter.book_id == book_id)
                .order_by(Chapter.ordinal)
                .execution_options(populate_existing=True)
            )
        )

    def _audit(self) -> AuditService:
        return AuditService(self._session, self._context)
