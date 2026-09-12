"""Фоновый перевод: `python -m app.worker`.

Отдельный процесс, а не задача внутри API. Разница не в изяществе:
перевод книги идёт часами, и выкат новой версии API не должен обрывать
работу на середине. Разделив их, выкат витрины и API становится тем, чем
он и должен быть, — перезапуском двух контейнеров, пока третий переводит.

Что процесс делает:

1. подбирает задания, брошенные убитыми рабочими;
2. забирает следующее из очереди — `FOR UPDATE SKIP LOCKED`, поэтому
   рабочих может быть сколько угодно и задание достаётся одному;
3. переводит книгу пачками, отмечаясь живым после каждой;
4. по готовности отправляет уведомление.

🔥 Сделанное фиксируется после каждой пачки. Из этого следует всё
остальное: убитый процесс, выкат, отмена и повтор после сбоя теряют не
перевод, а только незаконченную пачку — следующий заход продолжает с
остатка и не платит второй раз за переведённое.
"""

import asyncio
import logging
import os
import signal
import socket
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.document import Document
from app.models.job import JobState, TranslationJob
from app.models.organization import Membership, Role, User
from app.services.context import RequestContext
from app.services.errors import DomainError
from app.services.jobs import JobQueue
from app.services.notify import NotificationService, ready_message
from app.services.providers import get_provider
from app.services.review import ReviewService
from app.services.translation import TranslationService

logger = logging.getLogger("app.worker")


@dataclass(slots=True)
class Outcome:
    """Чем кончился один заход на задание.

    `WAITING` здесь — не сбой, а вежливый возврат: процесс попросили
    завершиться, и задание отдано обратно в очередь целым.
    """

    state: JobState
    done: int
    error: str | None = None
    # Повторять ли сорвавшееся. Отказ в правах и незаконченная
    # терминология повторятся точно так же — их повторять нечего.
    retry: bool = False


async def actor(session: AsyncSession, job: TranslationJob) -> RequestContext | None:
    """От чьего имени рабочий действует по этому заданию.

    От имени того, кто книгу и поставил: его права и есть ответ на вопрос,
    можно ли её переводить. Если его учётной записи больше нет — от имени
    владельца пространства: работа заказана организацией, а не человеком, и
    уволившийся сотрудник не повод бросить оплаченную книгу.
    """
    if job.requested_by_id is not None:
        row = (
            await session.execute(
                select(User, Membership.role)
                .join(Membership, Membership.user_id == User.id)
                .where(
                    User.id == job.requested_by_id,
                    Membership.organization_id == job.organization_id,
                )
            )
        ).first()

        if row is not None:
            user, role = row

            return RequestContext(user=user, organization_id=job.organization_id, role=role)

    owner = (
        await session.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == job.organization_id,
                Membership.role == Role.OWNER,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if owner is None:
        return None

    return RequestContext(user=owner, organization_id=job.organization_id, role=Role.OWNER)


async def run_job(
    session: AsyncSession,
    queue: JobQueue,
    job: TranslationJob,
    context: RequestContext,
    stop: asyncio.Event,
) -> Outcome:
    """Перевести книгу задания до конца — или до причины остановиться."""
    service = TranslationService(session, context, get_provider())
    batch = get_settings().worker_batch
    done = job.segments_done

    while True:
        if stop.is_set():
            # Процесс просят завершиться. Задание возвращается в очередь
            # сразу, а не по истечении порога молчания: так выкат стоит
            # секунд, а не четверти часа простоя.
            return Outcome(JobState.WAITING, done=done)

        try:
            chunk = await service.translate(job.document_id, limit=batch)
        except DomainError as error:
            # Доменный отказ — это правило, а не сбой: нет прав, не
            # закончена терминология, документ занят. Повтор даст тот же
            # ответ, и крутить его значит жечь время на заведомо известном.
            return Outcome(JobState.FAILED, done=done, error=str(error))
        except Exception as error:  # noqa: BLE001 — причина уходит в задание
            logger.exception("Задание %s: пачка сорвалась", job.id)

            return Outcome(JobState.FAILED, done=done, error=str(error), retry=True)

        done += chunk.total

        if await queue.heartbeat(job, done=done) is JobState.CANCELLED:
            logger.info("Задание %s остановлено человеком на %d сегментах", job.id, done)

            return Outcome(JobState.CANCELLED, done=done)

        if chunk.remaining == 0:
            return Outcome(JobState.DONE, done=done)

        if chunk.total == 0:
            # Остаток есть, а взять нечего — так быть не должно. Крутить
            # цикл вхолостую нельзя: он молотил бы базу до скончания века.
            return Outcome(
                JobState.FAILED,
                done=done,
                error=(
                    f"Перевод не двигается: непереведённых {chunk.remaining}, "
                    "а в работу не взято ни одного"
                ),
            )


async def announce(session: AsyncSession, job: TranslationJob, context: RequestContext) -> None:
    """Сообщить, что книга готова.

    Несработавшее уведомление не делает перевод несделанным: книга
    переведена и записана, а непосланное письмо — это непосланное письмо.
    Поэтому отказ канала попадает в журнал, а задание остаётся выполненным.
    """
    document = await session.get(Document, job.document_id)

    if document is None:
        return

    progress = await ReviewService(session, context).progress(job.document_id)

    requester = (
        await session.get(User, job.requested_by_id) if job.requested_by_id is not None else None
    )

    deliveries = await NotificationService(session).notify(
        job.organization_id,
        ready_message(
            title=document.title,
            document_id=document.id,
            translated=progress.translated,
            flagged=progress.flagged,
        ),
        requested_by_email=requester.email if requester is not None else None,
    )

    if not deliveries:
        logger.info("Задание %s: сообщать некуда — каналы не включены", job.id)

    for delivery in deliveries:
        logger.info(
            "Задание %s, уведомление «%s»: %s",
            job.id,
            delivery.channel,
            "отправлено" if delivery.sent else f"не отправлено — {delivery.detail}",
        )

    # Отметка ставится и тогда, когда ни один канал не сработал: она
    # означает «о готовности сообщили, чем смогли», а не «письмо дошло».
    # Иначе следующий проход рассылал бы заново.
    job.notified_at = datetime.now(UTC)
    await session.commit()


async def once(session: AsyncSession, worker: str, stop: asyncio.Event) -> bool:
    """Один оборот: подобрать брошенное, взять задание, сделать его.

    Сессия приходит снаружи, а не открывается внутри: оборот — это единица
    работы, и тот, кто им распоряжается, решает, в какой транзакции он
    идёт. Обычному запуску это даёт свежую сессию на оборот, тесту —
    возможность проверить оборот целиком, не поднимая процесс.

    Отвечает, была ли работа: пустая очередь — повод подождать, сделанное
    задание — повод сразу взять следующее.
    """
    queue = JobQueue(session, worker)

    await queue.revive_stale()
    job = await queue.claim_next()

    if job is None:
        return False

    logger.info("Задание %s: книга %s, заход %d", job.id, job.document_id, job.attempts)

    context = await actor(session, job)

    if context is None:
        await queue.fail(
            job,
            done=job.segments_done,
            error="Некому выполнить задание: в пространстве не осталось владельца",
            retry=False,
        )

        return True

    outcome = await run_job(session, queue, job, context, stop)

    if outcome.state is JobState.WAITING:
        await queue.release(job, done=outcome.done)
        logger.info("Задание %s возвращено в очередь: рабочий завершается", job.id)

        return False

    if outcome.state is JobState.FAILED:
        await queue.fail(
            job,
            done=outcome.done,
            error=outcome.error or "Перевод сорвался",
            retry=outcome.retry,
        )
        logger.warning("Задание %s: %s", job.id, outcome.error)

        return True

    await queue.finish(job, done=outcome.done, state=outcome.state)

    if outcome.state is JobState.DONE:
        logger.info("Задание %s: книга переведена, сегментов %d", job.id, outcome.done)

        try:
            await announce(session, job, context)
        except (SQLAlchemyError, OSError):
            logger.exception("Задание %s: не удалось сообщить о готовности", job.id)

    return True


def _listen_for_stop(stop: asyncio.Event) -> None:
    """Завершаться по сигналу, а не по убийству.

    Docker при остановке шлёт SIGTERM и ждёт; пойманный сигнал означает
    «допиши пачку и отдай задание», а не пойманный — обрыв на середине.
    """
    loop = asyncio.get_running_loop()

    def raise_flag() -> None:
        # Из обработчика сигнала — только через цикл событий: сам он
        # выполняется между байткодами и спящий `wait_for` не разбудит,
        # а значит рабочий заметил бы остановку лишь через паузу опроса.
        loop.call_soon_threadsafe(stop.set)

    for name in ("SIGTERM", "SIGINT"):
        # Windows знает не все сигналы, а разработка идёт и на нём.
        number = getattr(signal, name, None)

        if number is None:
            continue

        try:
            loop.add_signal_handler(number, stop.set)
        except NotImplementedError:
            # Windows: у цикла событий обработчиков сигналов нет вовсе.
            signal.signal(number, lambda *_: raise_flag())


async def serve() -> None:
    settings = get_settings()
    worker = f"{socket.gethostname()}:{os.getpid()}"
    stop = asyncio.Event()

    _listen_for_stop(stop)

    logger.info(
        "Рабочий %s начал: пачка %d сегментов, попыток %d, опрос раз в %d с",
        worker,
        settings.worker_batch,
        settings.worker_max_attempts,
        settings.worker_poll_seconds,
    )

    while not stop.is_set():
        try:
            # Своя сессия на оборот: одна на весь процесс копила бы в себе
            # все задания за сутки работы и объекты, которых давно нет.
            async with get_sessionmaker()() as session:
                busy = await once(session, worker, stop)
        except (SQLAlchemyError, OSError):
            # База недоступна — не повод падать: рабочий ждёт и пробует
            # снова. Перезапуск контейнера в цикле недоступную базу не
            # лечит, а журнал забивает.
            logger.exception("Рабочий %s: обращение к базе не удалось", worker)
            busy = False

        if busy:
            continue

        # Ожидание через событие, а не sleep: пришедший сигнал завершения
        # не должен ждать конца паузы. Истёкшее ожидание — это «очередь всё
        # ещё пуста», обычный ход дела, а не отказ.
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)

    logger.info("Рабочий %s остановлен", worker)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
