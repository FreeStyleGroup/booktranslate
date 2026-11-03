"""Фоновая работа: `python -m app.worker`.

Отдельный процесс, а не задача внутри API. Разница не в изяществе:
перевод книги идёт часами, и выкат новой версии API не должен обрывать
работу на середине. Разделив их, выкат витрины и API становится тем, чем
он и должен быть, — перезапуском двух контейнеров, пока третий переводит.

Что процесс делает:

1. подбирает задания, брошенные убитыми рабочими;
2. забирает следующее из очереди — `FOR UPDATE SKIP LOCKED`, поэтому
   рабочих может быть сколько угодно и задание достаётся одному;
3. переводит главу пачками, отмечаясь живым после каждой;
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
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models.job import JobKind, JobState, TranslationJob
from app.models.organization import Membership, Role, User
from app.models.qa import QAKind, QARun
from app.models.translation import TranslationRun
from app.services.artifacts import ArtifactService
from app.services.context import RequestContext
from app.services.errors import DomainError
from app.services.export.base import ExportError
from app.services.figures import FigureService
from app.services.jobs import JobQueue
from app.services.notify import NotificationService, ready_message
from app.services.providers import (
    STUB,
    get_figure_reader,
    get_provider,
    get_reviewer,
    provider_info,
    semantic_info,
)
from app.services.qa_runner import QARunner
from app.services.storage import get_storage
from app.services.translation_runner import Advance, TranslationRunner
from app.services.workspace import model_for

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
    """Выполнить задание: рабочий выбирает обработчик по виду работы."""
    if job.kind is JobKind.QA:
        return await run_qa(session, queue, job, context, stop)

    if job.kind is JobKind.RENDER:
        return await run_render(session, queue, job, context)

    if job.kind is JobKind.FIGURES:
        return await run_figures(session, queue, job, context)

    return await run_translation(session, queue, job, context, stop)


class WorkCancelledError(Exception):
    """Человек отменил работу, пока она шла."""


async def run_render(
    session: AsyncSession, queue: JobQueue, job: TranslationJob, context: RequestContext
) -> Outcome:
    """Собрать файлы выпуска. Сборка одним куском: кусками PDF не собрать."""
    if job.book_release_id is None:
        return Outcome(JobState.FAILED, done=0, error="Выпуск не указан")

    async def beat() -> None:
        if await queue.heartbeat(job, done=job.items_done) is JobState.CANCELLED:
            raise WorkCancelledError

    service = ArtifactService(session, context, get_storage())

    try:
        done = await service.render(job.book_release_id, tick=beat)
    except WorkCancelledError:
        await session.rollback()

        return Outcome(JobState.CANCELLED, done=0)
    except (DomainError, ExportError) as error:
        await session.rollback()

        return Outcome(JobState.FAILED, done=0, error=str(error))

    return Outcome(JobState.DONE, done=done)


async def run_figures(
    session: AsyncSession, queue: JobQueue, job: TranslationJob, context: RequestContext
) -> Outcome:
    """Прочитать и перевести надписи. Каждая картинка фиксируется сразу."""
    if job.chapter_id is None:
        return Outcome(JobState.FAILED, done=0, error="Глава не указана")

    async def beat(done: int) -> None:
        if await queue.heartbeat(job, done=done) is JobState.CANCELLED:
            raise WorkCancelledError

    model = await model_for(session, job.organization_id)
    service = FigureService(session, context, get_storage())

    try:
        done = await service.process(
            job.chapter_id,
            reader=get_figure_reader(model),
            provider=get_provider(model),
            tick=beat,
        )
    except WorkCancelledError:
        await session.rollback()

        return Outcome(JobState.CANCELLED, done=job.items_done)
    except (DomainError, ExportError) as error:
        await session.rollback()

        return Outcome(JobState.FAILED, done=job.items_done, error=str(error))

    return Outcome(JobState.DONE, done=done)


async def run_qa(
    session: AsyncSession,
    queue: JobQueue,
    job: TranslationJob,
    context: RequestContext,
    stop: asyncio.Event,
) -> Outcome:
    """Выполнить прогон проверки главы."""
    run = await session.get(QARun, job.qa_run_id)

    if run is None:
        return Outcome(JobState.FAILED, done=job.items_done, error="Прогон проверки не найден")

    reviewer = None

    if run.kind is QAKind.SEMANTIC:
        info = semantic_info(run.model)

        if (info.provider, info.prompt_version) != (run.provider, run.check_profile_version):
            return Outcome(
                JobState.FAILED,
                done=job.items_done,
                error="Настройки модели изменились после постановки в очередь: запустите заново.",
            )

        reviewer = get_reviewer(None if run.provider == STUB else run.model)

    runner = QARunner(session, context, get_storage(), reviewer)
    run_id = run.id

    return await _drive(
        session,
        queue,
        job,
        stop,
        lambda limit: runner.advance(run_id, limit=limit),
    )


async def run_translation(
    session: AsyncSession,
    queue: JobQueue,
    job: TranslationJob,
    context: RequestContext,
    stop: asyncio.Event,
) -> Outcome:
    """Выполнить прогон перевода главы — до конца или до причины остановиться."""
    run = await session.get(TranslationRun, job.run_id)

    if run is None:
        return Outcome(JobState.FAILED, done=job.items_done, error="Прогон перевода не найден")

    # Прогон записал, чем переводит. Настройки сменились, пока он ждал, — значит,
    # запись разошлась бы с тем, чем на самом деле переведено, а это та самая
    # история, ради которой она заведена.
    info = provider_info(run.model)

    if (info.provider, info.prompt_version) != (run.provider, run.prompt_version):
        return Outcome(
            JobState.FAILED,
            done=job.items_done,
            error=(
                "Настройки перевода изменились после постановки в очередь. Переведённое "
                "сохранено — запустите перевод заново."
            ),
        )

    runner = TranslationRunner(
        session, context, get_provider(None if run.provider == STUB else run.model)
    )
    run_id = run.id

    return await _drive(
        session,
        queue,
        job,
        stop,
        lambda limit: runner.advance(run_id, limit=limit),
    )


async def _drive(
    session: AsyncSession,
    queue: JobQueue,
    job: TranslationJob,
    stop: asyncio.Event,
    advance: Callable[[int], Awaitable[Advance]],
) -> Outcome:
    """Вести прогон пачками, отмечаясь живым после каждой: сделанное уже зафиксировано."""
    batch = get_settings().worker_batch
    done = job.items_done

    while True:
        if stop.is_set():
            return Outcome(JobState.WAITING, done=done)

        try:
            step = await advance(batch)
        except DomainError as error:
            await session.rollback()
            await session.refresh(job)

            return Outcome(JobState.FAILED, done=done, error=str(error))
        except Exception as error:  # noqa: BLE001 — причина уходит в задание
            logger.exception("Задание %s: порция сорвалась", job.id)
            await session.rollback()
            await session.refresh(job)

            return Outcome(JobState.FAILED, done=done, error=str(error), retry=True)

        done += step.processed

        if await queue.heartbeat(job, done=done) is JobState.CANCELLED:
            logger.info("Задание %s остановлено человеком на %d блоках", job.id, done)

            return Outcome(JobState.CANCELLED, done=done)

        if step.remaining == 0:
            return Outcome(JobState.DONE, done=done)

        if step.processed == 0:
            return Outcome(
                JobState.FAILED,
                done=done,
                error=f"Работа не двигается: осталось блоков {step.remaining}, не взято ни одного",
            )


async def announce(session: AsyncSession, job: TranslationJob) -> None:
    """Сообщить, что работа готова.

    Несработавшее уведомление не делает перевод несделанным: книга
    переведена и записана, а непосланное письмо — это непосланное письмо.
    Поэтому отказ канала попадает в журнал, а задание остаётся выполненным.
    """
    run = await session.get(TranslationRun, job.run_id)

    if run is None:
        return

    requester = (
        await session.get(User, job.requested_by_id) if job.requested_by_id is not None else None
    )

    deliveries = await NotificationService(session).notify(
        job.organization_id,
        ready_message(
            title=job.title,
            book_id=run.book_id,
            chapter_id=run.chapter_id,
            translated=run.from_model + run.from_memory + run.copied,
            rejected=len(run.rejections),
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

    logger.info("Задание %s: %s, заход %d", job.id, job.title, job.attempts)

    context = await actor(session, job)

    if context is None:
        await queue.fail(
            job,
            done=job.items_done,
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

    # О проверке не пишут: её заказали здесь и сейчас, а итог виден на странице главы.
    if outcome.state is JobState.DONE and job.kind is JobKind.QA:
        logger.info("Задание %s: глава проверена, блоков %d", job.id, outcome.done)

    if outcome.state is JobState.DONE and job.kind is JobKind.CHAPTER:
        logger.info("Задание %s: глава переведена, блоков %d", job.id, outcome.done)

        try:
            await announce(session, job)
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
        "Рабочий %s начал: пачка %d блоков, попыток %d, опрос раз в %d с",
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
