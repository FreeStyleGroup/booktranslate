"""Фоновый перевод: очередь, рабочий, уведомление.

Проверяется то, ради чего фон и заводился: глава переводится без человека и до конца;
закрытая вкладка ей не мешает; остановка не отменяет оплаченного; убитый рабочий не
запирает главу навсегда.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import JobState, TranslationJob
from app.worker import once
from tests.chapters import open_book
from tests.conftest import requires_database
from tests.factories import Account, register

# Шесть абзацев: хватает, чтобы рабочий взял главу не одной порцией, если порцию
# уменьшить, и чтобы счётчики были больше единицы.
BOOK = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Check the gauge every day.\n"
    b"\n"
    b"The service interval is 500 hours.\n"
    b"\n"
    b"Replace the filter cartridge.\n"
    b"\n"
    b"Close the valve after the test.\n"
)

STOP = asyncio.Event()


async def queued_chapter(client: AsyncClient, account: Account) -> tuple[str, dict]:
    """Глава, поставленная в очередь. Возвращает главу и задание."""
    book = await open_book(client, account, data=BOOK)
    started = await client.post(
        f"/chapters/{book.chapter}/translation", headers=account.headers, json={}
    )
    assert started.status_code == 201, started.text
    run = started.json()

    job = await client.get(f"/jobs/{run['job_id']}", headers=account.headers)
    assert job.status_code == 200, job.text

    return book.chapter, job.json()


async def work(session: AsyncSession, worker: str = "test") -> bool:
    """Один оборот рабочего на сессии теста."""
    return await once(session, worker, STOP)


async def job_row(session: AsyncSession, job_id: str) -> TranslationJob:
    job = await session.get(TranslationJob, uuid.UUID(job_id))
    assert job is not None
    await session.refresh(job)

    return job


@requires_database
async def test_queued_chapter_translates_without_a_human(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """То, ради чего всё это: глава переводится, пока человека нет."""
    account = await register(db_client)
    chapter_id, job = await queued_chapter(db_client, account)

    assert job["state"] == "waiting"
    assert job["kind"] == "chapter"
    assert job["items_total"] == 6
    assert job["items_done"] == 0

    assert await work(session) is True

    finished = await job_row(session, job["id"])

    assert finished.state is JobState.DONE
    assert finished.items_done == 6
    assert finished.attempts == 1
    assert finished.finished_at is not None
    assert finished.heartbeat_at is not None
    # Сообщить о готовности попытались: что каналы не настроены — не сбой.
    assert finished.notified_at is not None

    state = (
        await db_client.get(f"/chapters/{chapter_id}/translation", headers=account.headers)
    ).json()
    assert state["pending"] == 0


@requires_database
async def test_empty_queue_is_not_work(db_client: AsyncClient, session: AsyncSession) -> None:
    """Пустая очередь — повод подождать, а не крутить цикл."""
    await register(db_client)

    assert await work(session) is False


@requires_database
async def test_one_chapter_one_live_job(db_client: AsyncClient) -> None:
    """Двойное нажатие не заводит вторую очередь на ту же главу."""
    account = await register(db_client)
    chapter_id, _ = await queued_chapter(db_client, account)

    second = await db_client.post(
        f"/chapters/{chapter_id}/translation", headers=account.headers, json={}
    )

    assert second.status_code == 409, second.text
    assert "уже переводится" in second.json()["detail"]


@requires_database
async def test_finished_job_cannot_be_cancelled(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, job = await queued_chapter(db_client, account)

    await work(session)

    cancelled = await db_client.post(f"/jobs/{job['id']}/cancel", headers=account.headers)

    # Задание уже выполнено — останавливать нечего, и 200 здесь было бы молчаливым
    # согласием: человек решил бы, что перевод остановлен.
    assert cancelled.status_code == 409
    assert "уже закончено" in cancelled.json()["detail"]


@requires_database
async def test_waiting_job_can_be_cancelled(db_client: AsyncClient, session: AsyncSession) -> None:
    """Отменённое задание рабочий не берёт вовсе."""
    account = await register(db_client)
    chapter_id, job = await queued_chapter(db_client, account)

    cancelled = await db_client.post(f"/jobs/{job['id']}/cancel", headers=account.headers)

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"

    assert await work(session) is False

    state = (
        await db_client.get(f"/chapters/{chapter_id}/translation", headers=account.headers)
    ).json()
    assert state["translated"] == 0


@requires_database
async def test_dead_worker_does_not_lock_the_chapter(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """🔥 Убитый рабочий обязан отпустить главу, иначе она стоит вечно."""
    account = await register(db_client)
    _, queued = await queued_chapter(db_client, account)
    job = await job_row(session, queued["id"])

    # Задание, взятое рабочим, которого больше нет: отметка жизни давно не обновлялась.
    job.state = JobState.RUNNING
    job.worker = "погибший"
    job.attempts = 1
    job.heartbeat_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()

    assert await work(session, worker="живой") is True

    finished = await job_row(session, str(job.id))

    assert finished.state is JobState.DONE
    assert finished.items_done == 6


@requires_database
async def test_chapter_that_keeps_falling_is_given_up(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Иначе глава, роняющая каждый заход, крутилась бы в очереди вечно и за деньги."""
    account = await register(db_client)
    _, queued = await queued_chapter(db_client, account)
    job = await job_row(session, queued["id"])

    job.state = JobState.RUNNING
    job.worker = "погибший"
    # Попытки исчерпаны: следующий подбор обязан признать срыв, а не начать четвёртый заход.
    job.attempts = 3
    job.heartbeat_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()

    assert await work(session) is False

    finished = await job_row(session, str(job.id))

    assert finished.state is JobState.FAILED
    assert finished.error is not None
    assert "Переведённое сохранено" in finished.error


@requires_database
async def test_jobs_are_scoped_to_organization(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, job = await queued_chapter(db_client, account)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    assert (await db_client.get(f"/jobs/{job['id']}", headers=stranger.headers)).status_code == 404
    assert (
        await db_client.post(f"/jobs/{job['id']}/cancel", headers=stranger.headers)
    ).status_code == 404
    assert (await db_client.get("/jobs", headers=stranger.headers)).json() == []


@requires_database
async def test_job_list_shows_what_is_being_translated(db_client: AsyncClient) -> None:
    account = await register(db_client)
    chapter_id, _ = await queued_chapter(db_client, account)

    response = await db_client.get(
        "/jobs", headers=account.headers, params={"chapter_id": chapter_id}
    )
    jobs = response.json()

    assert response.status_code == 200, response.text
    assert len(jobs) == 1
    assert jobs[0]["chapter_id"] == chapter_id
    # Название — с заданием: по списку заданий человек понимает, что идёт, а
    # идентификатора ему для этого мало.
    assert jobs[0]["title"].startswith("CH01")
    assert jobs[0]["book_id"]


@requires_database
async def test_requested_by_is_remembered(db_client: AsyncClient, session: AsyncSession) -> None:
    """Кто поставил — тому и уведомление."""
    account = await register(db_client)
    _, queued = await queued_chapter(db_client, account)

    job = await session.scalar(
        select(TranslationJob).where(TranslationJob.id == uuid.UUID(queued["id"]))
    )

    assert job is not None
    assert job.requested_by_id == account.user_id
