"""Редакторский цикл через API.

Проверяется то, ради чего он устроен именно так: правка расходится по
повторам, но не трогает чужие решения; принятое отличается от
поправленного; книгу можно принять, не нажимая три тысячи раз.
"""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import Account, create_project, register

# Второй и четвёртый абзацы совпадают: правка одного обязана подтянуть
# второй, иначе книга разъедется там, где повтор переводился один раз.
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
    """Проект, документ, разбор и перевод — состояние, с которого начинается правка."""
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

    translated = await client.post(f"/documents/{document_id}/translate", headers=account.headers)
    assert translated.status_code == 200, translated.text

    return document_id


async def segments(
    client: AsyncClient, account: Account, document_id: str, **params: object
) -> list[dict]:
    response = await client.get(
        f"/documents/{document_id}/segments", headers=account.headers, params=params
    )
    assert response.status_code == 200, response.text
    items: list[dict] = response.json()["items"]

    return items


@requires_database
async def test_edit_marks_segment_and_records_author(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    items = await segments(db_client, account, document_id)

    response = await db_client.patch(
        f"/segments/{items[0]['id']}",
        headers=account.headers,
        json={"target_text": "Откройте клапан перед пуском."},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["segment"]["target_text"] == "Откройте клапан перед пуском."
    assert body["segment"]["status"] == "edited"
    # По этому полю через полгода видно, что строку писал человек, а не модель.
    assert body["segment"]["translation_source"] == "human"


@requires_database
async def test_edit_reaches_repeats(db_client: AsyncClient) -> None:
    """Повтор переводился один раз — и правиться обязан один раз."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    items = await segments(db_client, account, document_id)

    response = await db_client.patch(
        f"/segments/{items[1]['id']}",
        headers=account.headers,
        json={"target_text": "Внимание! Отключите питание."},
    )

    assert response.json()["propagated"] == 1

    updated = await segments(db_client, account, document_id)

    assert updated[3]["target_text"] == "Внимание! Отключите питание."
    assert updated[3]["status"] == "edited"
    # Соседний абзац про другое — его правка не касается.
    assert updated[2]["target_text"] != "Внимание! Отключите питание."


@requires_database
async def test_edit_does_not_touch_approved_repeat(db_client: AsyncClient) -> None:
    """За принятым сегментом стоит решение человека; чужая правка его не отменяет."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    items = await segments(db_client, account, document_id)

    approved = await db_client.post(f"/segments/{items[3]['id']}/approve", headers=account.headers)
    assert approved.status_code == 200, approved.text
    kept = approved.json()["target_text"]

    response = await db_client.patch(
        f"/segments/{items[1]['id']}",
        headers=account.headers,
        json={"target_text": "Внимание! Отключите питание."},
    )

    assert response.json()["propagated"] == 0

    updated = await segments(db_client, account, document_id)

    assert updated[3]["target_text"] == kept
    assert updated[3]["status"] == "approved"


@requires_database
async def test_edit_goes_to_memory(db_client: AsyncClient) -> None:
    """Исправленное однажды не переводится моделью заново в следующей книге."""
    account = await register(db_client)
    first = await prepare(db_client, account)
    items = await segments(db_client, account, first)

    await db_client.patch(
        f"/segments/{items[0]['id']}",
        headers=account.headers,
        json={"target_text": "Откройте клапан перед пуском."},
    )

    second = await prepare(db_client, account, data=b"Open the valve before start.\n")
    fresh = await segments(db_client, account, second)

    assert fresh[0]["target_text"] == "Откройте клапан перед пуском."
    assert fresh[0]["translation_source"] == "memory"


@requires_database
async def test_empty_edit_is_refused(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    items = await segments(db_client, account, document_id)

    response = await db_client.patch(
        f"/segments/{items[0]['id']}", headers=account.headers, json={"target_text": "   "}
    )

    assert response.status_code == 400


@requires_database
async def test_approve_clean_leaves_flagged_to_the_editor(db_client: AsyncClient) -> None:
    account = await register(db_client)

    # Регистр не совпадает с текстом: сопоставление термин найдёт, а
    # заглушка подставить не сможет — сегмент окажется помеченным.
    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "Pressure Gauge",
            "target_term": "манометр",
            "source_language": "en",
            "target_language": "ru",
            "status": "confirmed",
        },
    )

    document_id = await prepare(db_client, account)

    response = await db_client.post(
        f"/documents/{document_id}/segments/approve-clean", headers=account.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["approved"] == 3

    flagged = await segments(db_client, account, document_id, status="flagged")

    assert len(flagged) == 1
    assert "pressure gauge" in flagged[0]["source_text"].lower()


@requires_database
async def test_document_is_done_when_everything_is_approved(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    await db_client.post(
        f"/documents/{document_id}/segments/approve-clean", headers=account.headers
    )

    progress = (
        await db_client.get(f"/documents/{document_id}/progress", headers=account.headers)
    ).json()

    assert progress["total"] == 4
    assert progress["approved"] == 4
    assert progress["is_complete"] is True

    document = (await db_client.get(f"/documents/{document_id}", headers=account.headers)).json()

    assert document["status"] == "done"


@requires_database
async def test_reopen_returns_document_to_review(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    await db_client.post(
        f"/documents/{document_id}/segments/approve-clean", headers=account.headers
    )

    items = await segments(db_client, account, document_id)
    response = await db_client.post(f"/segments/{items[0]['id']}/reopen", headers=account.headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "edited"

    document = (await db_client.get(f"/documents/{document_id}", headers=account.headers)).json()

    assert document["status"] == "review"


@requires_database
async def test_worst_first_puts_findings_on_top(db_client: AsyncClient) -> None:
    """Редактор разбирает очередь замечаний, а не книгу подряд."""
    account = await register(db_client)

    await db_client.post(
        "/glossary",
        headers=account.headers,
        json={
            "source_term": "Pressure Gauge",
            "target_term": "манометр",
            "source_language": "en",
            "target_language": "ru",
            "status": "confirmed",
        },
    )

    document_id = await prepare(db_client, account)
    ordered = await segments(db_client, account, document_id, worst_first=True)

    assert "pressure gauge" in ordered[0]["source_text"].lower()
    assert ordered[0]["quality_score"] is not None
    assert ordered[-1]["quality_score"] is None


@requires_database
async def test_count_follows_the_filter(db_client: AsyncClient) -> None:
    """Иначе полоса прокрутки покажет тысячу там, где строк десять."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    items = await segments(db_client, account, document_id)

    await db_client.post(f"/segments/{items[0]['id']}/approve", headers=account.headers)

    response = await db_client.get(
        f"/documents/{document_id}/segments",
        headers=account.headers,
        params={"status": "approved"},
    )
    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1


@requires_database
async def test_segments_are_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    document_id = await prepare(db_client, owner)
    items = await segments(db_client, owner, document_id)

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")

    response = await db_client.patch(
        f"/segments/{items[0]['id']}",
        headers=stranger.headers,
        json={"target_text": "Чужая правка"},
    )

    assert response.status_code == 404


async def with_two_kinds_of_findings(client: AsyncClient, account: Account) -> str:
    """Книга, в которой проверки нашли разное.

    Нужна трём тестам сразу: отбору по виду находки, счётчику по видам и
    уходу принятого из очереди. Виды подобраны под заглушку: числа и
    подстановки она переносит дословно, придраться к ней может только
    словарь.

    Первая находка — термин заведён в другом регистре: сопоставление его
    найдёт, а подстановка по точному совпадению не сработает. Вторая —
    сокращение, которое положено раскрыть при первом употреблении: заглушка
    подставит перевод вместо него, и самого сокращения в переводе не
    останется.
    """
    for term in (
        {"source_term": "Pressure Gauge", "target_term": "манометр", "status": "confirmed"},
        {
            "source_term": "MM",
            "target_term": "маркет-мейкер",
            "kind": "abbreviation",
            "expand_on_first_use": True,
        },
    ):
        response = await client.post(
            "/glossary",
            headers=account.headers,
            json={**term, "source_language": "en", "target_language": "ru"},
        )
        assert response.status_code in (200, 201), response.text

    return await prepare(
        client,
        account,
        data=(
            b"Open the valve before start.\n"
            b"\n"
            b"Check the pressure gauge every day.\n"
            b"\n"
            b"The MM quotes prices for the whole session.\n"
        ),
    )


@requires_database
async def test_queue_is_filtered_by_kind_of_finding(db_client: AsyncClient) -> None:
    """Редактор разбирает очередь по видам: термины отдельно, раскрытие отдельно."""
    account = await register(db_client)
    document_id = await with_two_kinds_of_findings(db_client, account)

    response = await db_client.get(
        f"/documents/{document_id}/segments",
        headers=account.headers,
        params={"status": "flagged", "check": "glossary"},
    )
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert "pressure gauge" in body["items"][0]["source_text"].lower()

    checks = {finding["check"] for finding in body["items"][0]["quality"]["findings"]}
    assert "glossary" in checks


@requires_database
async def test_queue_filter_counts_the_whole_book(db_client: AsyncClient) -> None:
    """🔥 Число рядом с видом находки означает книгу, а не выданную страницу.

    Иначе редактор, увидев «термины — 1» при лимите в одну строку, решит,
    что работы осталось на одну строку.
    """
    account = await register(db_client)
    document_id = await with_two_kinds_of_findings(db_client, account)

    response = await db_client.get(
        f"/documents/{document_id}/segments",
        headers=account.headers,
        params={"status": "flagged", "limit": 1},
    )
    body = response.json()

    assert len(body["items"]) == 1
    assert body["total"] == 2


@requires_database
async def test_progress_counts_findings_by_kind(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await with_two_kinds_of_findings(db_client, account)

    progress = (
        await db_client.get(f"/documents/{document_id}/progress", headers=account.headers)
    ).json()

    assert progress["flagged"] == 2
    assert progress["by_check"]["glossary"] == 1
    assert progress["by_check"]["first_use"] == 1


@requires_database
async def test_accepted_segment_leaves_the_queue(db_client: AsyncClient) -> None:
    """Принятое перестаёт быть работой, хотя находки у него остаются."""
    account = await register(db_client)
    document_id = await with_two_kinds_of_findings(db_client, account)

    flagged = await segments(db_client, account, document_id, status="flagged", check="glossary")
    approved = await db_client.post(
        f"/segments/{flagged[0]['id']}/approve", headers=account.headers
    )

    assert approved.status_code == 200, approved.text
    # Находки сохраняются: видно, что было замечено и всё-таки принято.
    assert approved.json()["quality"] is not None

    progress = (
        await db_client.get(f"/documents/{document_id}/progress", headers=account.headers)
    ).json()

    assert "glossary" not in progress["by_check"]
    assert progress["by_check"]["first_use"] == 1


@requires_database
async def test_progress_has_no_findings_on_a_clean_book(db_client: AsyncClient) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)

    progress = (
        await db_client.get(f"/documents/{document_id}/progress", headers=account.headers)
    ).json()

    assert progress["by_check"] == {}
