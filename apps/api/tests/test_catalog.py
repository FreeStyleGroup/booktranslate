"""Каталог терминов через API.

Проверяется то, ради чего он заведён: незнакомое слово смотрят один раз,
ненайденное запоминается наравне с найденным, а справка не превращается в
решение сама собой.
"""

from httpx import AsyncClient

from app.services.providers import Explanation
from tests.conftest import requires_database
from tests.factories import Account, create_project, register
from tests.test_terminology import MANUAL, by_source, extract, prepare


async def lookup(client: AsyncClient, account: Account, terms: list[str], **extra: object) -> dict:
    response = await client.post(
        "/catalog/lookup",
        headers=account.headers,
        json={
            "terms": terms,
            "source_language": "en",
            "target_language": "ru",
            **extra,
        },
    )
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


@requires_database
async def test_lookup_records_the_answer(db_client: AsyncClient, lookup_log: list) -> None:
    account = await register(db_client)

    report = await lookup(db_client, account, ["basis risk"])

    assert report["asked"] == 1
    assert report["from_catalog"] == 0
    assert report["found"] == 1
    assert len(lookup_log) == 1

    entry = report["entries"][0]

    assert entry["source_term"] == "basis risk"
    assert entry["suggested_target"] == "перевод:basis risk"
    assert entry["sources"][0]["url"] == "https://example.org/term"
    assert entry["looked_up_by"] == "test-lookup"


@requires_database
async def test_known_term_is_not_asked_again(db_client: AsyncClient, lookup_log: list) -> None:
    """Ради этого каталог и заведён: за одну справку платят один раз."""
    account = await register(db_client)

    await lookup(db_client, account, ["basis risk"])
    report = await lookup(db_client, account, ["Basis Risk"])

    assert report["from_catalog"] == 1
    assert report["asked"] == 0
    # Регистр к справке отношения не имеет: спрашивать второй раз про то же
    # слово с заглавной — платить дважды.
    assert len(lookup_log) == 1
    assert report["entries"][0]["suggested_target"] == "перевод:basis risk"


@requires_database
async def test_refresh_asks_again(db_client: AsyncClient, lookup_log: list) -> None:
    """Справку иногда нужно переспросить — например когда прояснилась отрасль."""
    account = await register(db_client)

    await lookup(db_client, account, ["basis risk"])
    report = await lookup(db_client, account, ["basis risk"], refresh=True)

    assert report["asked"] == 1
    assert len(lookup_log) == 2

    listing = (await db_client.get("/catalog", headers=account.headers)).json()

    # Переспрошенное обновляет запись, а не заводит вторую.
    assert len(listing) == 1


@requires_database
async def test_not_found_is_remembered(
    db_client: AsyncClient, lookup_log: list, lookup_answers: dict
) -> None:
    """«Искали и не нашли» — тоже знание: без него каждая книга ищет заново."""
    account = await register(db_client)
    lookup_answers["squibble"] = Explanation(found=False, definition="нет в источниках")

    first = await lookup(db_client, account, ["squibble"])

    assert first["found"] == 0
    assert first["entries"][0]["found"] is False
    assert first["entries"][0]["definition"] == "нет в источниках"

    second = await lookup(db_client, account, ["squibble"])

    assert second["from_catalog"] == 1
    assert len(lookup_log) == 1


@requires_database
async def test_repeated_term_in_one_request_is_asked_once(
    db_client: AsyncClient, lookup_log: list
) -> None:
    account = await register(db_client)

    report = await lookup(db_client, account, ["slippage", "Slippage", "slippage"])

    assert report["asked"] == 1
    assert len(lookup_log) == 1
    assert len(report["entries"]) == 1


@requires_database
async def test_lookup_reports_what_it_cost(db_client: AsyncClient) -> None:
    """С живой моделью справки нельзя собирать вслепую."""
    account = await register(db_client)

    report = await lookup(db_client, account, ["slippage"])

    assert report["input_tokens"] == 1000
    assert report["output_tokens"] == 200
    # Поисковые запросы оплачиваются отдельно от токенов, и в счётчиках
    # токенов их не видно вовсе.
    assert report["searches"] == 1
    # Источник не в прейскуранте — и это честнее нуля.
    assert report["estimated_usd"] is None


@requires_database
async def test_document_lookup_takes_undecided_candidates(
    db_client: AsyncClient, lookup_log: list
) -> None:
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    await extract(db_client, account, document_id)

    response = await db_client.post(
        f"/documents/{document_id}/terminology/lookup", headers=account.headers, json={"limit": 2}
    )
    assert response.status_code == 200, response.text

    body = response.json()

    assert body["asked"] == 2
    # Самое частое идёт первым: слово, встреченное трижды, стоит справки
    # больше, чем случайное из подписи к рисунку.
    assert lookup_log[0].source_term == "check valve"
    # Отрывок уходит в запрос вместе с термином: одно и то же слово в разных
    # отраслях значит разное.
    assert "check valve" in lookup_log[0].sample
    assert lookup_log[0].subject is not None


@requires_database
async def test_decision_keeps_the_source_of_the_answer(db_client: AsyncClient) -> None:
    """Адрес, по которому термин посмотрели, обязан уехать в словарь."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    candidates = await extract(db_client, account, document_id)

    await db_client.post(
        f"/documents/{document_id}/terminology/lookup",
        headers=account.headers,
        json={"limit": 5},
    )

    valve = by_source(candidates, "check valve")
    decided = await db_client.post(
        f"/documents/{document_id}/terminology/decisions",
        headers=account.headers,
        json={
            "decisions": [
                {"candidate_id": valve["id"], "accept": True, "target_term": "обратный клапан"}
            ]
        },
    )
    assert decided.status_code == 200, decided.text

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    term = next(item for item in glossary if item["source_term"] == "check valve")

    assert term["reference"] == "https://example.org/term"


@requires_database
async def test_own_reference_wins_over_the_catalogue(db_client: AsyncClient) -> None:
    """Человек мог посмотреть термин в бумажном справочнике, которого в сети нет."""
    account = await register(db_client)
    document_id = await prepare(db_client, account)
    candidates = await extract(db_client, account, document_id)

    await db_client.post(
        f"/documents/{document_id}/terminology/lookup",
        headers=account.headers,
        json={"limit": 5},
    )

    await db_client.post(
        f"/documents/{document_id}/terminology/decisions",
        headers=account.headers,
        json={
            "decisions": [
                {
                    "candidate_id": by_source(candidates, "check valve")["id"],
                    "accept": True,
                    "target_term": "обратный клапан",
                    "reference": "ГОСТ 24856-2014",
                }
            ]
        },
    )

    glossary = (await db_client.get("/glossary", headers=account.headers)).json()
    term = next(item for item in glossary if item["source_term"] == "check valve")

    assert term["reference"] == "ГОСТ 24856-2014"


@requires_database
async def test_search_looks_into_definitions(db_client: AsyncClient) -> None:
    """Человек помнит смысл чаще, чем точное написание термина."""
    account = await register(db_client)
    await lookup(db_client, account, ["slippage"])

    found = await db_client.get("/catalog?query=Справка про slip", headers=account.headers)

    assert found.status_code == 200
    assert [item["source_term"] for item in found.json()] == ["slippage"]

    missing = await db_client.get("/catalog?query=валютный контроль", headers=account.headers)

    assert missing.json() == []


@requires_database
async def test_catalogue_is_scoped_to_organization(db_client: AsyncClient) -> None:
    owner = await register(db_client)
    await lookup(db_client, owner, ["basis risk"])

    stranger = await register(db_client, email="other@example.com", organization_name="Чужие")
    listing = await db_client.get("/catalog", headers=stranger.headers)

    assert listing.status_code == 200
    assert listing.json() == []


@requires_database
async def test_lookup_needs_a_project_language_pair(db_client: AsyncClient) -> None:
    """Справка привязана к языковой паре: en→ru и en→de — разные ответы."""
    account = await register(db_client)
    await lookup(db_client, account, ["basis risk"])

    response = await db_client.post(
        "/catalog/lookup",
        headers=account.headers,
        json={"terms": ["basis risk"], "source_language": "en", "target_language": "de"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["asked"] == 1


@requires_database
async def test_document_lookup_needs_the_document(db_client: AsyncClient) -> None:
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    assert project_id

    response = await db_client.post(
        f"/documents/{project_id}/terminology/lookup", headers=account.headers, json={}
    )

    assert response.status_code == 404


@requires_database
async def test_document_lookup_skips_decided_candidates(
    db_client: AsyncClient, lookup_log: list
) -> None:
    """По разобранному справка уже не нужна, а деньги стоит."""
    account = await register(db_client)
    document_id = await prepare(db_client, account, data=MANUAL)
    candidates = await extract(db_client, account, document_id)

    await db_client.post(
        f"/documents/{document_id}/terminology/decisions",
        headers=account.headers,
        json={
            "decisions": [
                {"candidate_id": by_source(candidates, "check valve")["id"], "accept": False}
            ]
        },
    )

    await db_client.post(
        f"/documents/{document_id}/terminology/lookup", headers=account.headers, json={}
    )

    assert "check valve" not in [request.source_term for request in lookup_log]
