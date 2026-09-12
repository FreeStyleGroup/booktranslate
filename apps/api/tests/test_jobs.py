"""Фоновый перевод: очередь, рабочий, уведомление.

Проверяется то, ради чего фон и заводился: книга переводится без человека
и до конца; закрытая вкладка ей не мешает; остановка не отменяет
оплаченного; убитый рабочий не запирает книгу навсегда.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import JobState, TranslationJob
from app.worker import once
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

# Шесть абзацев: хватает, чтобы рабочий взял книгу не одной пачкой, если
# пачку уменьшить, и чтобы счётчики были больше единицы.
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


async def parsed_book(client: AsyncClient, account: Account, *, data: bytes = BOOK) -> str:
    """Книга, разобранная на сегменты и готовая к переводу."""
    project_id = await create_project(client, account)

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("руководство.txt", data, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id: str = uploaded.json()["id"]

    parsed = await client.post(f"/documents/{document_id}/parse", headers=account.headers)
    assert parsed.status_code == 200, parsed.text

    return document_id


async def work(session: AsyncSession, worker: str = "test") -> bool:
    """Один оборот рабочего на сессии теста."""
    return await once(session, worker, STOP)


async def job_row(session: AsyncSession, job_id: str) -> TranslationJob:
    job = await session.get(TranslationJob, uuid.UUID(job_id))
    assert job is not None
    await session.refresh(job)

    return job


@requires_database
async def test_queued_book_translates_without_a_human(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """То, ради чего всё это: книга переводится, пока человека нет."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)

    assert queued.status_code == 201, queued.text
    job = queued.json()
    assert job["state"] == "waiting"
    assert job["segments_total"] == 6
    assert job["segments_done"] == 0

    assert await work(session) is True

    finished = await job_row(session, job["id"])

    assert finished.state is JobState.DONE
    assert finished.segments_done == 6
    assert finished.finished_at is not None
    # Уведомление отмечено даже без включённых каналов: отметка означает
    # «о готовности сообщили, чем смогли», и не даёт слать второй раз.
    assert finished.notified_at is not None

    progress = (
        await db_client.get(f"/documents/{document_id}/progress", headers=account.headers)
    ).json()

    assert progress["untouched"] == 0


@requires_database
async def test_empty_queue_is_not_work(db_client: AsyncClient, session: AsyncSession) -> None:
    """Пустая очередь — повод подождать, а не крутить обороты впустую."""
    await register(db_client)

    assert await work(session) is False


@requires_database
async def test_one_book_one_live_job(db_client: AsyncClient) -> None:
    """Двойное нажатие не заводит вторую очередь на ту же книгу."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    first = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    second = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert "уже стоит в очереди" in second.json()["detail"]


@requires_database
async def test_unparsed_book_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("руководство.txt", BOOK, "text/plain")},
    )
    document_id = uploaded.json()["id"]

    response = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)

    assert response.status_code == 409
    assert "не разобран" in response.json()["detail"]


@requires_database
async def test_translated_book_has_nothing_to_queue(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    await work(session)

    again = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)

    assert queued.status_code == 201
    assert again.status_code == 409
    assert "не осталось непереведённых" in again.json()["detail"]


@requires_database
async def test_cancel_keeps_what_was_paid_for(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Остановка отменяет продолжение, а не сделанное: за него заплачено."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    job_id = queued.json()["id"]

    await work(session)

    cancelled = await db_client.post(f"/jobs/{job_id}/cancel", headers=account.headers)

    # Задание уже выполнено — останавливать нечего, и это отказ, а не
    # молчаливое согласие: иначе человек решил бы, что перевод прерван.
    assert cancelled.status_code == 409
    assert "уже закончено" in cancelled.json()["detail"]


@requires_database
async def test_waiting_job_can_be_cancelled(db_client: AsyncClient, session: AsyncSession) -> None:
    """Отменённое задание рабочий не берёт вовсе."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    job_id = queued.json()["id"]

    cancelled = await db_client.post(f"/jobs/{job_id}/cancel", headers=account.headers)

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"

    # Очередь пуста: отменённое заданием больше не является.
    assert await work(session) is False

    progress = (
        await db_client.get(f"/documents/{document_id}/progress", headers=account.headers)
    ).json()

    assert progress["untouched"] == 6


@requires_database
async def test_dead_worker_does_not_lock_the_book(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """🔥 Убитый рабочий обязан отпустить книгу, иначе она застревает навсегда."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    job = await job_row(session, queued.json()["id"])

    # Задание, взятое рабочим, которого больше нет: отметка жизни давно
    # не обновлялась.
    job.state = JobState.RUNNING
    job.worker = "погибший"
    job.attempts = 1
    job.heartbeat_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()

    assert await work(session, worker="живой") is True

    finished = await job_row(session, str(job.id))

    assert finished.state is JobState.DONE
    assert finished.segments_done == 6


@requires_database
async def test_book_that_keeps_falling_is_given_up(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Иначе книга, роняющая каждый заход, крутилась бы вечно и тратила деньги."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    job = await job_row(session, queued.json()["id"])

    job.state = JobState.RUNNING
    job.worker = "погибший"
    # Попытки исчерпаны: следующий подбор обязан признать срыв, а не
    # начать четвёртый заход.
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
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)
    job_id = queued.json()["id"]

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    assert (await db_client.get(f"/jobs/{job_id}", headers=stranger.headers)).status_code == 404
    assert (
        await db_client.post(f"/jobs/{job_id}/cancel", headers=stranger.headers)
    ).status_code == 404
    assert (await db_client.get("/jobs", headers=stranger.headers)).json() == []


@requires_database
async def test_job_list_shows_the_book_history(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)

    response = await db_client.get(
        "/jobs", headers=account.headers, params={"document_id": document_id}
    )
    jobs = response.json()

    assert response.status_code == 200, response.text
    assert len(jobs) == 1
    assert jobs[0]["document_id"] == document_id


@requires_database
async def test_requested_by_is_remembered(db_client: AsyncClient, session: AsyncSession) -> None:
    """Кто поставил книгу — тому и уведомление, и его правами она переводится."""
    account = await register(db_client)
    document_id = await parsed_book(db_client, account)

    queued = await db_client.post(f"/documents/{document_id}/queue", headers=account.headers)

    assert queued.json()["requested_by_id"] == str(account.user_id)

    job = await session.scalar(
        select(TranslationJob).where(TranslationJob.document_id == uuid.UUID(document_id))
    )
    assert job is not None
    assert job.requested_by_id == account.user_id
