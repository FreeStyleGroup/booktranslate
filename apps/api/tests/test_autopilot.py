"""Автоматический режим: тот же конвейер, остановка там, где нужен человек."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker
from app.models.audit import AuditEvent
from app.models.autopilot import AutopilotRun
from app.services.autopilot import claim_next
from app.services.providers.base import ProviderError
from app.services.providers.semantic import SemanticRequest, StubReviewer
from app.services.source_validation import FileFacts
from app.services.storage import LocalStorage
from tests.conftest import requires_database
from tests.factories import Account, create_project, epub_bytes, register
from tests.test_chapter_translation import CHAPTER, SECOND, STOP, ready, translate
from tests.test_figures import GOOD, UNSURE, Reader, picture
from tests.test_issues import act, registered
from tests.test_release_gate import audit_all, rendered
from tests.test_releases import approved, prepared
from tests.test_reviews import start
from tests.test_team import accept_as_new, invite, token_of

STEP_LIMIT = 120

FIGURE = (
    '<figure><img src="scheme.png" alt="Scheme"/><figcaption>Figure 1. Scheme</figcaption></figure>'
)


@pytest.fixture(autouse=True)
def worker_storage(monkeypatch: pytest.MonkeyPatch, storage_root: Path) -> None:
    monkeypatch.setattr(worker, "get_storage", lambda: LocalStorage(storage_root))


async def book_with(
    client: AsyncClient, account: Account, *, figure: bool = False
) -> tuple[str, str]:
    project_id = await create_project(client, account)
    created = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "Pumps"}
    )
    book_id: str = created.json()["id"]
    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={
            "file": (
                "pumps.epub",
                epub_bytes(
                    [
                        ("part01.xhtml", CHAPTER + (FIGURE if figure else "")),
                        ("part02.xhtml", SECOND),
                    ],
                    assets={"scheme.png": picture()} if figure else None,
                ),
                "application/epub+zip",
            )
        },
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    return project_id, book_id


async def launch(client: AsyncClient, account: Account, book_id: str, **body: object) -> dict:
    # Порог высокий: в тестах модель-заглушка не подставляет термины, а обязательных тут и нет.
    payload = {"term_min_frequency": 1000, **body}
    response = await client.post(
        f"/books/{book_id}/autopilot", headers=account.headers, json=payload
    )
    assert response.status_code == 201, response.text

    run: dict = response.json()["run"]
    return run


async def read(client: AsyncClient, account: Account, book_id: str) -> dict:
    response = await client.get(f"/books/{book_id}/autopilot", headers=account.headers)
    assert response.status_code == 200, response.text

    run: dict = response.json()["run"]
    return run


async def drive(session: AsyncSession, client: AsyncClient, account: Account, book_id: str) -> dict:
    """Крутить рабочий, пока прогон не закончится или не остановится."""
    for _ in range(STEP_LIMIT):
        while await worker.once(session, "test", STOP):
            pass

        await worker.advance_autopilot(session)
        run = await read(client, account, book_id)

        if run["status"] != "running":
            return run

    raise AssertionError(f"Прогон не закончился: {run}")


@requires_database
async def test_one_button_goes_from_upload_to_pass(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)

    run = await launch(db_client, account, book_id)
    assert run["status"] == "running"

    run = await drive(session, db_client, account, book_id)
    assert run["status"] == "done", run["waiting"]
    assert run["stage"] == "done"
    assert run["chapters_total"] == run["chapters_done"] == 2
    assert all(stage["state"] == "done" for stage in run["stages"])

    gate = (
        await db_client.get(f"/releases/{run['release_id']}/gate", headers=account.headers)
    ).json()
    assert gate["status"] == "passed"
    assert gate["ready"] is True
    assert gate["automatic"] is True
    assert gate["snapshot"]["automatic"] is True

    files = (
        await db_client.get(
            f"/book-releases/{run['release_id']}/artifacts", headers=account.headers
        )
    ).json()
    assert {row["format"] for row in files["artifacts"]} == {"docx", "pdf"}

    pdf = next(row for row in files["artifacts"] if row["format"] == "pdf")
    pages = (await db_client.get(f"/artifacts/{pdf['id']}/pages", headers=account.headers)).json()
    assert {row["status"] for row in pages} == {"auto_pass"}

    book = (await db_client.get(f"/books/{book_id}", headers=account.headers)).json()
    assert book["status"] == "released"


@requires_database
async def test_every_decision_is_written_as_automatic(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)
    await launch(db_client, account, book_id)
    await drive(session, db_client, account, book_id)

    kinds = {
        row.kind: row
        for row in await session.scalars(
            select(AuditEvent).where(AuditEvent.kind.like("autopilot.%"))
        )
    }
    for kind in (
        "autopilot.started",
        "autopilot.source_validated",
        "autopilot.boundaries_approved",
        "autopilot.master_approved",
        "autopilot.glossary_approved",
        "autopilot.review_completed",
        "autopilot.chapter_released",
        "autopilot.book_built",
        "autopilot.finished",
    ):
        assert kind in kinds, kind
        assert kinds[kind].payload["automatic"] is True


@requires_database
async def test_manifest_is_the_same_as_manual_one(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    """Расхождение между режимами значило бы, что автомат пошёл мимо конвейера.

    Книга и глоссарий у обоих прогонов одинаковые: от него зависит текст перевода.
    """
    account = await register(db_client)
    book_id, _ = await ready(db_client, account)
    await launch(db_client, account, book_id)
    await drive(session, db_client, account, book_id)

    structure = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)
    chapter = structure.json()["chapters"][0]["id"]
    release = (
        await db_client.get(f"/chapters/{chapter}/releases", headers=account.headers)
    ).json()[0]
    manifest = (
        await db_client.get(f"/chapter-releases/{release['id']}/manifest", headers=account.headers)
    ).json()
    assert manifest["intact"] is True

    other = await register(db_client, email="manual@example.com", organization_name="Вручную")
    _, chapters = await prepared(db_client, session, other)
    made = await db_client.post(
        f"/chapters/{chapters[0]['id']}/releases", headers=other.headers, json={}
    )
    assert made.status_code == 201, made.text
    manual = (
        await db_client.get(
            f"/chapter-releases/{made.json()['id']}/manifest", headers=other.headers
        )
    ).json()

    assert set(manifest["manifest"]) == set(manual["manifest"])
    assert manifest["manifest"]["automatic"] is True
    assert manual["manifest"]["automatic"] is False

    def blocks_of(body: dict) -> list[tuple[str, str]]:
        return [(row["code"], row["text_sha256"]) for row in body["manifest"]["blocks"]]

    assert blocks_of(manifest) == blocks_of(manual)


@requires_database
async def test_reviews_say_that_no_human_looked(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)
    await launch(db_client, account, book_id)
    await drive(session, db_client, account, book_id)

    structure = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)
    chapter = structure.json()["chapters"][0]["id"]
    reviews = (await db_client.get(f"/chapters/{chapter}/reviews", headers=account.headers)).json()

    for kind in ("technical", "literary", "final_compare"):
        assert reviews[kind]["automatic"] is True, kind
        assert reviews[kind]["status"] == "completed", kind


@requires_database
async def test_open_critical_issue_stops_and_resume_continues(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, chapters = await prepared(db_client, session, account)
    # Книга уже прошла редактуру руками: автомат подхватит её с нынешнего состояния.
    book = (await db_client.get("/books", headers=account.headers)).json()
    items = book["items"] if isinstance(book, dict) else book
    book_id = items[0]["id"]

    rows = (
        await db_client.get(
            f"/chapters/{chapters[0]['id']}/translation/blocks?limit=5", headers=account.headers
        )
    ).json()["items"]
    issue = await registered(db_client, account, rows[0], severity="critical")

    await launch(db_client, account, book_id)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert [row["issue_id"] for row in run["waiting"]] == [issue["id"]]
    assert issue["code"] in run["waiting"][0]["message"]
    assert run["stage"] != "done"

    # Закрывать замечание сервис не умеет: продолжение без решения остановится снова.
    resumed = await db_client.post(
        f"/autopilot-runs/{run['id']}/resume", headers=account.headers, json={}
    )
    assert resumed.status_code == 200, resumed.text
    run = await drive(session, db_client, account, book_id)
    assert run["status"] == "waiting_human"

    await act(db_client, account, issue["id"], "reject", note="Проверено, не ошибка")
    await db_client.post(f"/autopilot-runs/{run['id']}/resume", headers=account.headers, json={})
    run = await drive(session, db_client, account, book_id)
    assert run["status"] == "done", run["waiting"]


@requires_database
async def test_confident_figure_goes_through_and_unsure_stops(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "get_figure_reader", lambda model=None: Reader(GOOD))
    account = await register(db_client)
    _, book_id = await book_with(db_client, account, figure=True)
    await launch(db_client, account, book_id)
    run = await drive(session, db_client, account, book_id)
    assert run["status"] == "done", run["waiting"]

    second = await register(db_client, email="second@example.com", organization_name="Вторые")
    monkeypatch.setattr(worker, "get_figure_reader", lambda model=None: Reader(UNSURE))
    _, other = await book_with(db_client, second, figure=True)
    await launch(db_client, second, other)
    run = await drive(session, db_client, second, other)

    assert run["status"] == "waiting_human"
    assert run["waiting"][0]["code"] == "figure_needs_human"
    assert run["waiting"][0]["figures"] is True


@requires_database
async def test_budget_stops_before_spending(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)

    async def too_much(self: object, chapter_id: object) -> float:
        return 100.0

    monkeypatch.setattr("app.services.autopilot.AutopilotService._estimate", too_much)

    await launch(db_client, account, book_id, budget_usd=1.0)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert run["waiting"][0]["code"] == "over_budget"
    assert run["stage"] == "terms"

    translation = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)
    first = translation.json()["chapters"][0]["id"]
    state = (await db_client.get(f"/chapters/{first}/translation", headers=account.headers)).json()
    assert state["translated"] == 0


@requires_database
async def test_provider_failure_stops_instead_of_guessing(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        name = "broken"

        async def translate(self, requests: list[object]) -> object:
            raise ProviderError("Модель недоступна")

    monkeypatch.setattr(worker, "get_provider", lambda model=None: Broken())
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)

    await launch(db_client, account, book_id, term_min_frequency=2)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert "Модель недоступна" in run["waiting"][0]["message"]


@requires_database
async def test_unreadable_source_stops_the_book(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.source_validation.read_facts",
        lambda path, source_format: FileFacts(format_ok=False, has_text_layer=False),
    )
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)

    await launch(db_client, account, book_id)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert run["waiting"][0]["code"] == "source_invalid"
    assert "pumps.epub" in run["waiting"][0]["message"]

    structure = await db_client.get(f"/books/{book_id}/chapters", headers=account.headers)
    assert structure.json()["chapters"] == []


@requires_database
async def test_unknown_price_does_not_pass_the_budget(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)

    async def unknown(self: object, chapter_id: object) -> None:
        return None

    monkeypatch.setattr("app.services.autopilot.AutopilotService._estimate", unknown)

    await launch(db_client, account, book_id, budget_usd=1.0)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert run["waiting"][0]["code"] == "unknown_price"


@requires_database
async def test_failed_meaning_check_stops_instead_of_counting_as_done(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Refusing(StubReviewer):
        async def review(self, requests: list[SemanticRequest]) -> object:
            raise ProviderError("Модель отказалась")

    monkeypatch.setattr(worker, "get_reviewer", lambda model=None: Refusing())
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)

    await launch(db_client, account, book_id)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert run["waiting"][0]["code"] == "semantic_incomplete"


@requires_database
async def test_work_opened_by_a_person_is_not_taken_over(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await ready(db_client, account)
    await translate(db_client, session, account, chapters[0]["id"])
    await start(db_client, account, chapters[0]["id"], "technical")

    await launch(db_client, account, book_id)
    run = await drive(session, db_client, account, book_id)

    assert run["status"] == "waiting_human"
    assert "ведёт человек" in run["waiting"][0]["message"]


@requires_database
async def test_button_pressed_by_a_person_does_not_hide_the_automatic_work(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    book_id, chapters = await prepared(db_client, session, account)
    await session.execute(
        text("UPDATE review_runs SET automatic = true WHERE chapter_id = :id"),
        {"id": chapters[0]["id"]},
    )
    session.expire_all()

    releases = [await approved(db_client, account, row["id"]) for row in chapters]
    manifests = [
        (
            await db_client.get(f"/chapter-releases/{row['id']}/manifest", headers=account.headers)
        ).json()["manifest"]
        for row in releases
    ]
    assert [row["automatic"] for row in manifests] == [True, False]

    built = await db_client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [row["id"] for row in releases]},
    )
    assert built.status_code == 201, built.text
    release_id = built.json()["id"]

    pdf = await rendered(db_client, session, account, release_id)
    await audit_all(db_client, account, pdf)
    passed = await db_client.post(f"/releases/{release_id}/pass", headers=account.headers)
    assert passed.status_code == 200, passed.text
    assert passed.json()["automatic"] is True
    assert passed.json()["snapshot"]["automatic"] is True


@requires_database
async def test_second_start_and_cancel(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)
    run = await launch(db_client, account, book_id)

    again = await db_client.post(f"/books/{book_id}/autopilot", headers=account.headers, json={})
    assert again.status_code == 409

    cancelled = await db_client.post(f"/autopilot-runs/{run['id']}/cancel", headers=account.headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["run"]["status"] == "cancelled"

    # Отменённый прогон сервис больше не трогает.
    await worker.advance_autopilot(session)
    assert (await read(db_client, account, book_id))["stage"] == "structure"

    twice = await db_client.post(f"/autopilot-runs/{run['id']}/cancel", headers=account.headers)
    assert twice.status_code == 409


@requires_database
async def test_lease_keeps_a_second_worker_away(
    db_client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)
    await launch(db_client, account, book_id)

    assert await claim_next(session) is not None
    assert await claim_next(session) is None

    row = await session.scalar(select(AutopilotRun).where(AutopilotRun.book_id == book_id))
    assert row is not None
    assert row.lease_until is not None


@requires_database
async def test_roles_and_isolation(db_client: AsyncClient, session: AsyncSession) -> None:
    account = await register(db_client)
    _, book_id = await book_with(db_client, account)
    run = await launch(db_client, account, book_id)

    invited = await invite(db_client, account, role="translator")
    translator = await accept_as_new(db_client, token_of(invited))
    refused = await db_client.post(f"/autopilot-runs/{run['id']}/cancel", headers=translator)
    assert refused.status_code == 403

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")
    for method, path in (
        ("GET", f"/books/{book_id}/autopilot"),
        ("POST", f"/autopilot-runs/{run['id']}/cancel"),
    ):
        response = await db_client.request(method, path, headers=stranger.headers)
        assert response.status_code == 404, path
