"""Перевод через API.

Проверяется то, за что придётся отвечать деньгами: повторы внутри документа
переводятся один раз, память закрывает то, что уже переводилось, а термин,
которого нет в переводе, помечает сегмент. И то, за что придётся отвечать
временем: книга переводится порциями до нуля, срыв на середине не теряет
оплаченного, а документ, брошенный убитым процессом, не запирается навсегда.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.organization import Role, User
from app.services.context import RequestContext
from app.services.memory import TranslationMemory
from app.services.providers import (
    ProviderError,
    StubProvider,
    Translated,
    TranslationRequest,
    Usage,
)
from app.services.translation import TranslationService, recover_interrupted
from tests.conftest import requires_database
from tests.factories import Account, create_project, register

# Второй и четвёртый абзацы совпадают: в руководствах предупреждение
# повторяется десятками раз, и платить за него дважды незачем.
MANUAL = (
    b"Open the valve before start.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
    b"\n"
    b"Check the pressure gauge.\n"
    b"\n"
    b"Warning! Disconnect the power supply.\n"
)


async def prepare(client: AsyncClient, account: Account, *, data: bytes = MANUAL) -> str:
    """Проект, загруженный документ и разбор — то, с чего начинается перевод."""
    project_id = await create_project(client, account)

    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", data, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id: str = uploaded.json()["id"]

    parsed = await client.post(f"/documents/{document_id}/parse", headers=account.headers)
    assert parsed.status_code == 200, parsed.text

    return document_id


async def mark(
    session: AsyncSession,
    document_id: str,
    status: DocumentStatus,
    *,
    silent_for: timedelta = timedelta(0),
) -> None:
    """Оставить документ в состоянии, которое ставит процесс и снимает он же.

    Так выглядит документ после убитого контейнера: отметка стоит, а
    снять её некому. `silent_for` — сколько он уже молчит.
    """
    await session.execute(
        update(Document)
        .where(Document.id == uuid.UUID(document_id))
        .values(status=status, updated_at=datetime.now(UTC) - silent_for)
    )
    await session.commit()


async def document_status(session: AsyncSession, document_id: str) -> DocumentStatus:
    document = await session.get(Document, uuid.UUID(document_id))
    assert document is not None
    await session.refresh(document)

    return document.status


@requires_database
async def test_repeats_are_translated_once(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    response = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total"] == 4
    # Четыре сегмента, но три разных текста: повтор предупреждения переведён
    # один раз, и это ровно то, за что не заплачено.
    assert body["unique_texts"] == 3
    assert body["saved_calls"] == 1
    # Книга уместилась в одну порцию: остатка нет, документ ждёт человека.
    assert body["remaining"] == 0
    assert body["status"] == "review"

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert segments[1]["target_text"] == segments[3]["target_text"]
    assert all(item["target_text"] for item in segments)
    assert segments[0]["translation_source"] == "stub"


@requires_database
async def test_second_document_is_taken_from_memory(db_client: AsyncClient) -> None:
    """Тот же текст в другом документе не отправляется модели во второй раз."""
    account = await register(db_client)

    first = await prepare(db_client, account)
    await db_client.post(f"/documents/{first}/translate", headers=account.headers)

    second = await prepare(db_client, account, data=MANUAL + b"\nOne more paragraph.\n")
    response = await db_client.post(f"/documents/{second}/translate", headers=account.headers)

    body = response.json()

    assert body["from_memory"] == 4
    # Модели достался единственный новый абзац.
    assert body["from_provider"] == 1
    assert body["saved_calls"] == 4

    segments = (
        await db_client.get(f"/documents/{second}/segments", headers=account.headers)
    ).json()["items"]

    assert segments[0]["status"] == "memory"
    assert segments[0]["translation_source"] == "memory"


@requires_database
async def test_glossary_term_reaches_provider(db_client: AsyncClient) -> None:
    """Термин из словаря подставлен — значит он доехал до провайдера."""
    account = await register(db_client)

    added = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "valve",
            "target_term": "клапан",
            "source_language": "en",
            "target_language": "ru",
        },
    )
    assert added.status_code == 201, added.text

    document_id = await prepare(db_client, account)
    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    assert "клапан" in segments[0]["target_text"]
    assert segments[0]["status"] == "machine"


@requires_database
async def test_unused_term_flags_segment(db_client: AsyncClient) -> None:
    """Заглушка подставляет термин дословно, а требуется другая форма."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "pressure gauge",
            "target_term": "манометр",
            "source_language": "en",
            "target_language": "ru",
            "mandatory": True,
        },
    )

    # Термин заведён так, что заглушка его не подставит: в тексте он есть,
    # а в переводе появиться неоткуда.
    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "start",
            "target_term": "пуск",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    document_id = await prepare(db_client, account, data=b"Open the valve before start.\n")
    result = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert result.json()["flagged"] == 0

    segments = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]

    # Заглушка подставила «пуск», поэтому претензий нет — проверка отработала
    # и не подняла ложную тревогу.
    assert "пуск" in segments[0]["target_text"]
    assert segments[0]["quality"] is None


@requires_database
async def test_repeat_run_does_not_touch_edited(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)
    again = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    # Все сегменты уже переведены: брать в работу нечего, и документ
    # остаётся каким был — на вычитке, а не «разобран».
    assert again.json()["total"] == 0
    assert again.json()["remaining"] == 0
    assert again.json()["status"] == "review"


@requires_database
async def test_book_is_translated_in_pages_until_nothing_remains(db_client: AsyncClient) -> None:
    """Прокси режет запрос через четверть часа: книга идёт порциями до нуля."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    first = await db_client.post(
        f"/documents/{document_id}/translate?limit=2", headers=account.headers
    )

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["total"] == 2
    assert body["remaining"] == 2
    # Пока остаток есть, документ «разобран»: следующий вызов его продолжит.
    assert body["status"] == "parsed"

    items = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]
    # Порция — начало книги, а не что попало: соседям это важно.
    assert [item["status"] for item in items] == ["machine", "machine", "new", "new"]

    second = await db_client.post(
        f"/documents/{document_id}/translate?limit=2", headers=account.headers
    )

    body = second.json()
    assert body["total"] == 2
    assert body["remaining"] == 0
    assert body["status"] == "review"
    # Повтор предупреждения из первой порции нашёлся в памяти: порции не
    # ломают экономию на повторах, она просто идёт через память.
    assert body["from_memory"] == 1
    assert body["from_provider"] == 1

    third = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)
    assert third.json()["total"] == 0


@requires_database
async def test_page_above_maximum_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    maximum = get_settings().translation_max_segments_per_run
    response = await db_client.post(
        f"/documents/{document_id}/translate?limit={maximum + 1}", headers=account.headers
    )

    assert response.status_code == 400
    assert "TRANSLATION_MAX_SEGMENTS_PER_RUN" in response.json()["detail"]


@requires_database
async def test_stale_run_is_released_only_with_force(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Документ, брошенный убитым процессом, лечится без перезапуска."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await mark(session, document_id, DocumentStatus.TRANSLATING, silent_for=timedelta(hours=2))

    plain = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    # Без force — отказ, но с подсказкой: человек должен понять, что делать.
    assert plain.status_code == 409
    assert "force=true" in plain.json()["detail"]

    forced = await db_client.post(
        f"/documents/{document_id}/translate?force=true", headers=account.headers
    )

    assert forced.status_code == 200, forced.text
    assert forced.json()["total"] == 4
    assert forced.json()["status"] == "review"


@requires_database
async def test_ordinary_run_raises_no_alarm(
    db_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """🔥 Тревога о перехвате зависшего прогона не должна звучать на обычном.

    Ловушка тонкая: обновление через ORM сверяет условие по объектам в
    сессии и подтягивает изменения в сам объект. Проверка «а не был ли
    документ уже занят», сделанная после обновления, видит собственную
    запись и срабатывает всегда. Предупреждение, звучащее на каждом
    запуске, перестают читать — и вместе с ним пропустят настоящее.
    """
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    with caplog.at_level(logging.WARNING, logger="app.services.translation"):
        response = await db_client.post(
            f"/documents/{document_id}/translate", headers=account.headers
        )

    assert response.status_code == 200, response.text
    assert [record.message for record in caplog.records] == []


@requires_database
async def test_taking_over_a_stale_run_is_reported(
    db_client: AsyncClient, session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """А на настоящем перехвате — обязана: это след чужого убитого процесса."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await mark(session, document_id, DocumentStatus.TRANSLATING, silent_for=timedelta(hours=2))

    with caplog.at_level(logging.WARNING, logger="app.services.translation"):
        response = await db_client.post(
            f"/documents/{document_id}/translate?force=true", headers=account.headers
        )

    assert response.status_code == 200, response.text
    assert any("взят повторно" in record.message for record in caplog.records)


@requires_database
async def test_live_run_is_not_released_by_force(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Прогон, отмечавшийся минуту назад, жив: второй запуск удвоил бы счёт."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await mark(session, document_id, DocumentStatus.TRANSLATING, silent_for=timedelta(minutes=1))

    forced = await db_client.post(
        f"/documents/{document_id}/translate?force=true", headers=account.headers
    )

    assert forced.status_code == 409
    assert "force=true" not in forced.json()["detail"]


@requires_database
async def test_startup_settles_interrupted_documents(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """После перезапуска отметки «разбирается» и «переводится» снимаются по данным."""
    account = await register(db_client)

    # Перевод прервался на середине: часть сегментов переведена и оплачена.
    halfway = await prepare(db_client, account)
    await db_client.post(f"/documents/{halfway}/translate?limit=2", headers=account.headers)
    await mark(session, halfway, DocumentStatus.TRANSLATING)

    # Прервался в самом конце: непереведённых уже не осталось.
    finished = await prepare(db_client, account, data=b"Close the valve.\n")
    await db_client.post(f"/documents/{finished}/translate", headers=account.headers)
    await mark(session, finished, DocumentStatus.TRANSLATING)

    # Разбор прервался до записи сегментов: их нет вовсе.
    project_id = await create_project(db_client, account)
    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("empty.txt", b"Text.\n", "text/plain")},
    )
    unparsed: str = uploaded.json()["id"]
    await mark(session, unparsed, DocumentStatus.PARSING)

    recovered = await recover_interrupted(session)

    settled = {str(item.document_id): item.status for item in recovered}
    assert settled[halfway] is DocumentStatus.PARSED
    assert settled[finished] is DocumentStatus.REVIEW
    assert settled[unparsed] is DocumentStatus.UPLOADED
    assert await document_status(session, halfway) is DocumentStatus.PARSED

    # Восстановленный документ продолжается с того места, где упал.
    resumed = await db_client.post(f"/documents/{halfway}/translate", headers=account.headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["total"] == 2
    assert resumed.json()["remaining"] == 0


class FailingProvider(StubProvider):
    """Провайдер, отказывающий на заданном по счёту обращении.

    Расход у него ненулевой, в отличие от заглушки: проверяется как раз то,
    что оплаченное до отказа попадает в учёт.
    """

    def __init__(self, fail_on_call: int) -> None:
        self._fail_on_call = fail_on_call
        self.calls = 0

    async def translate(self, requests: list[TranslationRequest]) -> Translated:
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise ProviderError("модель недоступна")

        answer = await super().translate(requests)

        return Translated(texts=answer.texts, usage=Usage(input_tokens=10, output_tokens=5))


@requires_database
async def test_failed_batch_keeps_earlier_batches(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Отказ на второй пачке не отменяет первую: она переведена, оплачена и в памяти."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    user = await session.get(User, account.user_id)
    assert user is not None
    context = RequestContext(user=user, organization_id=account.organization_id, role=Role.OWNER)

    settings = get_settings()
    batch_size = settings.translation_batch_size
    # По одному тексту в пачке: три разных текста — три обращения, второе падает.
    settings.translation_batch_size = 1
    provider = FailingProvider(fail_on_call=2)

    try:
        with pytest.raises(ProviderError):
            await TranslationService(session, context, provider).translate(uuid.UUID(document_id))
    finally:
        settings.translation_batch_size = batch_size

    # Первая пачка зафиксирована: сегмент переведён, расход учтён, память знает текст.
    items = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]
    assert [item["status"] for item in items] == ["machine", "new", "new", "new"]

    document = await session.scalar(select(Document).where(Document.id == uuid.UUID(document_id)))
    assert document is not None
    await session.refresh(document)
    assert document.input_tokens == 10
    assert document.output_tokens == 5
    # Отметка «переводится» снята по данным: остались непереведённые.
    assert document.status is DocumentStatus.PARSED

    known = await TranslationMemory(session, context).lookup(
        [items[0]["source_text"]], source_language="en", target_language="ru"
    )
    assert len(known) == 1

    # Следующий вызов продолжает с места срыва, а не отвечает «уже переводится».
    resumed = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["total"] == 3
    assert resumed.json()["remaining"] == 0
    assert resumed.json()["status"] == "review"


@requires_database
async def test_force_restarts_only_a_finished_document(db_client: AsyncClient) -> None:
    """Сброс — на переведённом целиком; с остатком force просто продолжает."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    await db_client.post(f"/documents/{document_id}/translate?limit=2", headers=account.headers)

    # Остаток есть: force не сбрасывает только что переведённое — иначе цикл
    # клиента, передающий force каждый раз, не кончался бы никогда.
    continued = await db_client.post(
        f"/documents/{document_id}/translate?force=true&limit=2", headers=account.headers
    )
    assert continued.json()["total"] == 2
    assert continued.json()["remaining"] == 0

    approved = await db_client.post(
        f"/documents/{document_id}/segments/approve-clean", headers=account.headers
    )
    assert approved.status_code == 200, approved.text

    # Остатка нет: force сбрасывает всё, включая принятое, и переводит заново.
    restarted = await db_client.post(
        f"/documents/{document_id}/translate?force=true&limit=3", headers=account.headers
    )
    assert restarted.json()["total"] == 3
    assert restarted.json()["remaining"] == 1
    assert restarted.json()["status"] == "parsed"

    items = (
        await db_client.get(f"/documents/{document_id}/segments", headers=account.headers)
    ).json()["items"]
    assert [item["status"] for item in items] == ["memory", "memory", "memory", "new"]


@requires_database
async def test_untranslated_document_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)

    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("manual.txt", MANUAL, "text/plain")},
    )
    document_id = uploaded.json()["id"]

    response = await db_client.post(f"/documents/{document_id}/translate", headers=account.headers)

    assert response.status_code == 409


@requires_database
async def test_glossary_is_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    await db_client.post(
        "/glossary",
        headers=owner.headers,
        json={
            "source_term": "valve",
            "target_term": "клапан",
            "source_language": "en",
            "target_language": "ru",
        },
    )

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    listing = await db_client.get("/glossary", headers=stranger.headers)

    assert listing.status_code == 200
    assert listing.json()["items"] == []


@requires_database
async def test_do_not_translate_requires_same_string(db_client: AsyncClient) -> None:
    account = await register(db_client)

    response = await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "USB",
            "target_term": "УСБ",
            "source_language": "en",
            "target_language": "ru",
            "kind": "do_not_translate",
        },
    )

    assert response.status_code == 400
