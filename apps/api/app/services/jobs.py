"""Очередь заданий на перевод.

Два разных пользователя у одного кода, и разделены они намеренно.

`JobService` работает от имени человека: ставит книгу в очередь, показывает
её задания, останавливает их. Всё — в границах его рабочего пространства.

`JobQueue` работает от имени фонового процесса, у которого ни запроса, ни
организации нет: он забирает следующее задание по всей базе. Смешать их в
одном классе значило бы дать запросу метод, который ходит мимо
мультитенантности, — и однажды его кто-нибудь вызовет.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.job import LIVE, JobState, TranslationJob
from app.models.organization import Role
from app.models.segment import Segment, SegmentStatus
from app.services.base import TenantService
from app.services.errors import ConflictError, NotFoundError
from app.services.terminology import TerminologyService

logger = logging.getLogger(__name__)

# Ставить книгу в очередь — та же работа, что переводить её вручную.
QUEUEING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)

# Состояния документа, из которых перевод запускать нечего.
NOT_PARSED = (DocumentStatus.UPLOADED, DocumentStatus.PARSING, DocumentStatus.FAILED)


class JobService(TenantService):
    async def enqueue(self, document_id: uuid.UUID) -> TranslationJob:
        """Поставить книгу в очередь на перевод.

        Всё, что помешает переводу, спрашивается здесь, а не откладывается
        до рабочего: задание, которое заведомо сорвётся через минуту,
        человеку бесполезно — он узнает о том же самом, но позже и в виде
        отказа, которого не просил.

        Правила при этом не переписываются: незаконченный терминологический
        проход считает та же служба, что и перевод. Второго места, где
        записано «сколько кандидатов без решения», не заводится.
        """
        self._context.require(*QUEUEING_ROLES)

        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )
        if document is None:
            raise NotFoundError("Документ не найден")

        if document.status in NOT_PARSED:
            raise ConflictError("Документ ещё не разобран на сегменты")

        untranslated = await self._untranslated(document_id)

        if untranslated == 0:
            raise ConflictError("В книге не осталось непереведённых сегментов")

        undecided = await TerminologyService(self._session, self._context).undecided(document_id)

        if undecided:
            raise ConflictError(
                f"Терминологический проход не закончен: {undecided} кандидатов без решения"
            )

        job = TranslationJob(
            organization_id=self.organization_id,
            document_id=document_id,
            state=JobState.WAITING,
            requested_by_id=self._context.user.id,
            segments_total=untranslated,
        )
        self._session.add(job)

        try:
            await self._session.commit()
        except IntegrityError as error:
            # Одна книга — одно живое задание; ограничение стоит в базе.
            # Два одновременных нажатия проходят проверку оба, и отличить
            # повтор от настоящей ошибки можно только здесь.
            await self._session.rollback()

            existing = await self._session.scalar(
                self.scoped(TranslationJob).where(
                    TranslationJob.document_id == document_id,
                    TranslationJob.state.in_(list(LIVE)),
                )
            )
            if existing is not None:
                raise ConflictError("Книга уже стоит в очереди на перевод") from error

            raise

        await self._session.refresh(job)

        return job

    async def list(
        self, *, document_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[TranslationJob]:
        """Задания пространства — новые сверху."""
        query: Select[tuple[TranslationJob]] = self.scoped(TranslationJob)

        if document_id is not None:
            query = query.where(TranslationJob.document_id == document_id)

        return list(
            await self._session.scalars(
                query.order_by(TranslationJob.created_at.desc()).limit(limit)
            )
        )

    async def get(self, job_id: uuid.UUID) -> TranslationJob:
        job = await self._session.scalar(
            self.scoped(TranslationJob).where(TranslationJob.id == job_id)
        )
        if job is None:
            raise NotFoundError("Задание не найдено")

        return job

    async def cancel(self, job_id: uuid.UUID) -> TranslationJob:
        """Остановить задание.

        Остановка не отменяет сделанного: переведённое зафиксировано после
        каждой пачки и остаётся переведённым. Отменяется только продолжение
        — и это надо понимать буквально, потому что за сделанное уже
        заплачено.

        Работающее задание останавливается не сразу: рабочий смотрит на
        состояние между пачками. Ждать здесь его нечего — состояние
        записано, и он его увидит.
        """
        self._context.require(*QUEUEING_ROLES)

        job = await self.get(job_id)

        if job.state not in LIVE:
            raise ConflictError("Это задание уже закончено")

        job.state = JobState.CANCELLED
        job.finished_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(job)

        return job

    async def _untranslated(self, document_id: uuid.UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(Segment)
                .where(
                    Segment.organization_id == self.organization_id,
                    Segment.document_id == document_id,
                    Segment.status == SegmentStatus.NEW,
                )
            )
            or 0
        )


class JobQueue:
    """Очередь глазами фонового процесса.

    Мультитенантности здесь нет намеренно: рабочий обслуживает всю базу, и
    организация у него берётся из задания, а не из запроса. Поэтому класс
    отдельный — чтобы этот обход границ был виден по имени, а не спрятан
    среди обычных методов.
    """

    def __init__(self, session: AsyncSession, worker: str) -> None:
        self._session = session
        self._worker = worker

    async def claim_next(self) -> TranslationJob | None:
        """Забрать следующее задание — ровно одно и ровно одному рабочему.

        `FOR UPDATE SKIP LOCKED` — то, ради чего очередь и живёт в базе:
        два рабочих, пришедшие одновременно, получают разные задания, а не
        одно на двоих. Без `SKIP LOCKED` второй ждал бы первого, и вся
        затея с несколькими рабочими теряла бы смысл.
        """
        now = datetime.now(UTC)

        chosen = (
            select(TranslationJob.id)
            .where(TranslationJob.state == JobState.WAITING)
            .order_by(TranslationJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )

        claimed = await self._session.execute(
            update(TranslationJob)
            .where(TranslationJob.id == chosen)
            .values(
                state=JobState.RUNNING,
                worker=self._worker,
                # Время начала — от первого захода: повтор после сбоя
                # продолжает ту же работу, и сдвигать её начало значит
                # потерять, сколько она идёт на самом деле.
                started_at=func.coalesce(TranslationJob.started_at, now),
                heartbeat_at=now,
                attempts=TranslationJob.attempts + 1,
                error=None,
            )
            .returning(TranslationJob.id)
        )

        job_id = claimed.scalar_one_or_none()
        await self._session.commit()

        if job_id is None:
            return None

        return await self._session.get(TranslationJob, job_id)

    async def revive_stale(self) -> int:
        """Вернуть в очередь задания убитых рабочих.

        Отметка жизни ставится после каждой пачки, поэтому молчание дольше
        порога — это убитый процесс, а не длинная пачка. Задание
        возвращается в ожидание, и его берёт кто угодно, включая того же
        рабочего после перезапуска: сделанное зафиксировано, заход
        продолжится с остатка.

        Задание, исчерпавшее попытки, не возвращается, а признаётся
        сорвавшимся: иначе книга, которую роняет каждый заход, крутилась бы
        в очереди вечно и тратила деньги на каждом.
        """
        options = get_settings()
        now = datetime.now(UTC)
        deadline = now - timedelta(minutes=options.worker_stale_minutes)

        dead = (
            TranslationJob.state == JobState.RUNNING,
            TranslationJob.heartbeat_at < deadline,
        )

        given_up = await self._session.execute(
            update(TranslationJob)
            .where(*dead, TranslationJob.attempts >= options.worker_max_attempts)
            .values(
                state=JobState.FAILED,
                finished_at=now,
                error=(
                    "Перевод обрывался "
                    f"{options.worker_max_attempts} раза подряд. Переведённое "
                    "сохранено — запустите книгу заново, она продолжит с остатка."
                ),
            )
        )

        returned = await self._session.execute(
            update(TranslationJob).where(*dead).values(state=JobState.WAITING, worker=None)
        )

        await self._session.commit()

        revived = int(returned.rowcount or 0)
        failed = int(given_up.rowcount or 0)

        if revived or failed:
            logger.warning(
                "Заданий подобрано у пропавших рабочих: %d, признано сорвавшимися: %d",
                revived,
                failed,
            )

        return revived

    async def heartbeat(self, job: TranslationJob, *, done: int) -> JobState:
        """Отметиться живым и узнать, не отменили ли задание.

        Одним запросом, потому что вопрос один: задание всё ещё моё и всё
        ещё нужно? Ответ — состояние из базы; «отменено» значит остановиться
        после этой пачки.
        """
        job.heartbeat_at = datetime.now(UTC)
        job.segments_done = done

        await self._session.commit()
        await self._session.refresh(job)

        return job.state

    async def finish(self, job: TranslationJob, *, done: int, state: JobState) -> None:
        job.state = state
        job.segments_done = done
        job.finished_at = datetime.now(UTC)

        await self._session.commit()

    async def release(self, job: TranslationJob, *, done: int) -> None:
        """Вернуть задание в очередь целым: рабочий завершается.

        Не то же самое, что срыв, и считается иначе: заход, отданный по
        просьбе завершиться, попытку не тратит. Иначе выкат трижды подряд
        объявил бы книгу сорвавшейся, ничего при этом не сломав.

        Возврат немедленный, а не по истечении порога молчания: так выкат
        стоит секунд простоя, а не четверти часа.
        """
        job.state = JobState.WAITING
        job.worker = None
        job.attempts = max(0, job.attempts - 1)
        job.segments_done = done

        await self._session.commit()

    async def fail(self, job: TranslationJob, *, done: int, error: str, retry: bool) -> None:
        """Записать срыв — и решить, будет ли ещё заход.

        Повтор безопасен для кошелька: переведённое фиксируется после
        каждой пачки, и следующий заход начинает с остатка. Поэтому
        повторяется всё, кроме того, что повторится точно так же: отказ в
        правах, незаконченная терминология, неразобранный документ. Это
        решает вызывающий — он один видит, какая именно ошибка пришла.
        """
        attempts_left = job.attempts < get_settings().worker_max_attempts

        job.segments_done = done
        job.error = error

        if retry and attempts_left:
            job.state = JobState.WAITING
            job.worker = None
        else:
            job.state = JobState.FAILED
            job.finished_at = datetime.now(UTC)

        await self._session.commit()
