"""Перевод надписей на рисунках: оригинал не меняется, неуверенное не проходит само."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker
from app.services.export.base import ExportError
from app.services.export.images import replace_images
from app.services.export.overlay import OverlayText, image_size, overlay
from app.services.providers.base import ProviderError, Usage
from app.services.providers.figures import (
    FigureReading,
    ReadRegion,
    StubFigureReader,
    parse_regions,
    prepare_image,
)
from app.services.storage import LocalStorage
from tests.conftest import requires_database
from tests.factories import Account, create_project, epub_bytes, register
from tests.test_chapter_translation import CHAPTER, STOP, translate
from tests.test_glossary_versions import approve, collect, decide, draft, extract_master
from tests.test_releases import approved as approve_release
from tests.test_releases import reviewed
from tests.test_team import accept_as_new, invite, token_of


def picture(size: tuple[int, int] = (400, 300), kind: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buffer, format=kind)

    return buffer.getvalue()


# ── перерисовка: без базы ──


def test_overlay_keeps_format_and_size_and_does_not_touch_original() -> None:
    for kind, media in (("PNG", "image/png"), ("JPEG", "image/jpeg")):
        original = picture(kind=kind)
        before = hashlib.sha256(original).hexdigest()

        drawn = overlay(original, [OverlayText("a", 10, 10, 200, 60, "Клапан")])

        assert drawn.media_type == media
        assert drawn.overflow == []
        assert drawn.content != original
        assert image_size(drawn.content) == (400, 300)
        assert hashlib.sha256(original).hexdigest() == before


def test_overlay_really_draws_inside_the_box() -> None:
    drawn = overlay(picture(), [OverlayText("a", 10, 10, 200, 60, "Клапан")])
    image = Image.open(io.BytesIO(drawn.content)).convert("L")

    inside = image.crop((10, 10, 210, 70)).getextrema()
    outside = image.crop((250, 150, 390, 290)).getextrema()
    assert inside[0] < 128
    assert outside == (255, 255)


def test_text_that_does_not_fit_is_reported() -> None:
    drawn = overlay(
        picture(), [OverlayText("a", 10, 10, 30, 10, "Очень длинная подпись которая не влезет")]
    )

    assert drawn.overflow == ["a"]


def test_box_outside_the_picture_is_reported() -> None:
    drawn = overlay(picture(), [OverlayText("a", 900, 900, 50, 50, "Текст")])

    assert drawn.overflow == ["a"]


def test_broken_image_is_refused() -> None:
    with pytest.raises(ExportError):
        overlay(b"not an image", [])


def test_replace_images_swaps_only_the_named_part() -> None:
    old = picture()
    new = picture(size=(10, 10))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/media/image1.png", old)
        archive.writestr("word/media/image2.png", b"other")
        archive.writestr("word/document.xml", "<xml/>")

    result = replace_images(buffer.getvalue(), {hashlib.sha256(old).hexdigest(): new})

    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.read("word/media/image1.png") == new
        assert archive.read("word/media/image2.png") == b"other"
        assert archive.read("word/document.xml") == b"<xml/>"


def test_regions_outside_the_scale_are_dropped() -> None:
    raw = (
        '{"regions": ['
        '{"x": 10, "y": 10, "w": 100, "h": 50, "text": "Valve", "confidence": 0.9},'
        '{"x": 950, "y": 10, "w": 100, "h": 50, "text": "Out", "confidence": 0.9},'
        '{"x": 10, "y": 10, "w": 100, "h": 50, "text": "   ", "confidence": 0.9}'
        "]}"
    )

    regions = parse_regions(raw)
    assert [row.text for row in regions] == ["Valve"]


def test_broken_answer_is_a_provider_error() -> None:
    with pytest.raises(ProviderError):
        parse_regions("вот ваши надписи")


def test_image_is_shrunk_for_the_model() -> None:
    sent, media = prepare_image(picture(size=(4000, 2000)))

    assert media == "image/png"
    assert Image.open(io.BytesIO(sent)).size == (1568, 784)


# ── глава с рисунком ──


class Reader:
    """Распознаватель с заданным ответом."""

    name = "test-reader"

    def __init__(self, regions: list[ReadRegion] | Exception) -> None:
        self._regions = regions

    async def read(self, content: bytes, media_type: str) -> FigureReading:
        if isinstance(self._regions, Exception):
            raise self._regions

        return FigureReading(regions=self._regions, usage=Usage(input_tokens=50, output_tokens=5))


GOOD = [ReadRegion(x=25, y=33, w=500, h=200, text="Valve", confidence=0.95)]
UNSURE = [ReadRegion(x=25, y=33, w=500, h=200, text="Va?ve", confidence=0.3)]


@pytest.fixture(autouse=True)
def worker_storage(monkeypatch: pytest.MonkeyPatch, storage_root: Path) -> None:
    monkeypatch.setattr(worker, "get_storage", lambda: LocalStorage(storage_root))


def use_reader(monkeypatch: pytest.MonkeyPatch, reader: object) -> None:
    monkeypatch.setattr(worker, "get_figure_reader", lambda model=None: reader)


async def figure_chapter(
    client: AsyncClient, account: Account, *, image: bytes | None = None
) -> tuple[str, str]:
    project_id = await create_project(client, account)
    created = await client.post(
        f"/projects/{project_id}/books", headers=account.headers, json={"title": "Pumps"}
    )
    book_id: str = created.json()["id"]
    body = (
        CHAPTER + '<figure><img src="scheme.png" alt="Scheme"/>'
        "<figcaption>Figure 1. Scheme</figcaption></figure>"
    )
    uploaded = await client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={
            "file": (
                "pumps.epub",
                epub_bytes(
                    [("part01.xhtml", body)],
                    assets={"scheme.png": image or picture()},
                ),
                "application/epub+zip",
            )
        },
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    for step in ("proposal", "approval"):
        response = await client.post(f"/books/{book_id}/chapters/{step}", headers=account.headers)
        assert response.status_code == 200, response.text

    chapter_id: str = response.json()["chapters"][0]["id"]
    master = await extract_master(client, account, chapter_id)
    approved = await client.post(f"/masters/{master['id']}/approval", headers=account.headers)
    assert approved.status_code == 200, approved.text
    await decide(client, account, chapter_id, await collect(client, account, chapter_id))
    version = await draft(client, account, book_id)
    status, answer = await approve(client, account, version["id"], reason="Терминов в книге нет")
    assert status == 200, answer

    return book_id, chapter_id


async def state(client: AsyncClient, account: Account, chapter_id: str) -> dict:
    response = await client.get(f"/chapters/{chapter_id}/figures", headers=account.headers)
    assert response.status_code == 200, response.text

    body: dict = response.json()
    return body


async def read_figures(
    client: AsyncClient, session: AsyncSession, account: Account, chapter_id: str
) -> dict:
    started = await client.post(
        f"/chapters/{chapter_id}/figures/translate", headers=account.headers
    )
    assert started.status_code == 202, started.text
    assert await worker.once(session, "test", STOP) is True

    return await state(client, account, chapter_id)


@requires_database
async def test_figure_needs_a_decision(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)

    body = await state(db_client, account, chapter_id)
    assert body["undecided"] == 1
    assert body["images"][0]["current"] is None
    assert body["images"][0]["code"].startswith("CH01-FIG")


@requires_database
async def test_confident_reading_is_translated_and_drawn(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(GOOD))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)

    body = await read_figures(db_client, session, account, chapter_id)
    row = body["images"][0]["current"]
    assert row["status"] == "draft"
    assert row["needs_human"] is False
    assert row["has_asset"] is True
    assert row["regions"][0]["source_text"] == "Valve"
    assert row["regions"][0]["target_text"]
    # Тысячные доли пересчитаны в точки настоящей картинки 400×300.
    assert (row["regions"][0]["x"], row["regions"][0]["y"]) == (10, 9)

    image = await db_client.get(f"/figure-translations/{row['id']}/image", headers=account.headers)
    assert image.status_code == 200
    assert image.headers["x-content-type-options"] == "nosniff"
    assert image.content != picture()

    # Решения пока нет: сервис только предложил.
    assert body["undecided"] == 1


@requires_database
async def test_unsure_reading_needs_a_human(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(UNSURE))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)

    row = (await read_figures(db_client, session, account, chapter_id))["images"][0]["current"]
    assert row["needs_human"] is True


@requires_database
async def test_no_text_is_a_decision_and_failure_is_not(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader([]))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)

    body = await read_figures(db_client, session, account, chapter_id)
    assert body["images"][0]["current"]["status"] == "no_text"
    assert body["undecided"] == 0

    other = await register(db_client, email="second@example.com", organization_name="Вторые")
    use_reader(monkeypatch, Reader(ProviderError("Модель отказалась")))
    _, second = await figure_chapter(db_client, other)
    body = await read_figures(db_client, session, other, second)
    row = body["images"][0]["current"]
    assert row["status"] == "draft"
    assert row["needs_human"] is True
    assert "Модель отказалась" in row["note"]
    assert body["undecided"] == 1


@requires_database
async def test_edit_makes_a_new_version_and_old_stays(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(GOOD))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)
    row = (await read_figures(db_client, session, account, chapter_id))["images"][0]["current"]
    region = row["regions"][0]
    payload = {
        "regions": [
            {
                "id": region["id"],
                "x": region["x"],
                "y": region["y"],
                "w": region["w"],
                "h": region["h"],
                "source_text": region["source_text"],
                "target_text": "Клапан",
            }
        ]
    }

    edited = await db_client.put(
        f"/figure-translations/{row['id']}/regions", headers=account.headers, json=payload
    )
    assert edited.status_code == 200, edited.text
    new = edited.json()
    assert new["version"] == row["version"] + 1
    assert new["regions"][0]["origin"] == "human"

    # Правка по устаревшей версии — конфликт, а не затирание.
    stale = await db_client.put(
        f"/figure-translations/{row['id']}/regions", headers=account.headers, json=payload
    )
    assert stale.status_code == 409

    old_image = await db_client.get(
        f"/figure-translations/{row['id']}/image", headers=account.headers
    )
    assert old_image.status_code == 200

    refused = await db_client.post(
        f"/figure-translations/{row['id']}/approve", headers=account.headers
    )
    assert refused.status_code == 409


@requires_database
async def test_text_that_does_not_fit_blocks_approval(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(GOOD))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)
    row = (await read_figures(db_client, session, account, chapter_id))["images"][0]["current"]
    region = row["regions"][0]

    edited = await db_client.put(
        f"/figure-translations/{row['id']}/regions",
        headers=account.headers,
        json={
            "regions": [
                {
                    "id": region["id"],
                    "x": region["x"],
                    "y": region["y"],
                    "w": 20,
                    "h": 10,
                    "source_text": region["source_text"],
                    "target_text": "Очень длинная подпись которая не поместится",
                }
            ]
        },
    )
    new = edited.json()
    assert new["needs_human"] is True
    assert new["regions"][0]["overflow"] is True

    refused = await db_client.post(
        f"/figure-translations/{new['id']}/approve", headers=account.headers
    )
    assert refused.status_code == 409
    assert "не поместился" in refused.json()["detail"]


@requires_database
async def test_keep_original_is_a_recorded_decision(db_client: AsyncClient) -> None:
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)
    image = (await state(db_client, account, chapter_id))["images"][0]

    kept = await db_client.post(
        f"/objects/{image['object_id']}/images/{image['index']}/keep-original",
        headers=account.headers,
        json={"note": "Подписи на схеме не переводятся по договору"},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["status"] == "kept_original"

    body = await state(db_client, account, chapter_id)
    assert body["undecided"] == 0


@requires_database
async def test_decided_row_is_immutable_in_the_database(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(GOOD))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)
    row = (await read_figures(db_client, session, account, chapter_id))["images"][0]["current"]

    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE figure_translations SET regions = '[]'::jsonb WHERE id = :id"),
                {"id": row["id"]},
            )

    approved = await db_client.post(
        f"/figure-translations/{row['id']}/approve", headers=account.headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    for statement in (
        "UPDATE figure_translations SET status = 'DRAFT' WHERE id = :id",
        "DELETE FROM figure_translations WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(text(statement), {"id": row["id"]})


@requires_database
async def test_figures_hold_the_chapter_release_and_translated_picture_goes_out(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(GOOD))
    account = await register(db_client)
    book_id, chapter_id = await figure_chapter(db_client, account)

    gate = await db_client.get(f"/chapters/{chapter_id}/release-gate", headers=account.headers)
    assert "figures_undecided" in {row["code"] for row in gate.json()["blockers"]}

    row = (await read_figures(db_client, session, account, chapter_id))["images"][0]["current"]
    approved = await db_client.post(
        f"/figure-translations/{row['id']}/approve", headers=account.headers
    )
    assert approved.status_code == 200, approved.text

    gate = await db_client.get(f"/chapters/{chapter_id}/release-gate", headers=account.headers)
    assert "figures_undecided" not in {item["code"] for item in gate.json()["blockers"]}

    await translate(db_client, session, account, chapter_id)
    await reviewed(db_client, session, account, chapter_id)
    release = await approve_release(db_client, account, chapter_id)

    manifest = (
        await db_client.get(f"/chapter-releases/{release['id']}/manifest", headers=account.headers)
    ).json()["manifest"]
    assert manifest["figures"][0]["status"] == "approved"
    assert manifest["figures"][0]["translation_id"] == row["id"]

    built = await db_client.post(
        f"/books/{book_id}/releases",
        headers=account.headers,
        json={"chapter_release_ids": [release["id"]]},
    )
    assert built.status_code == 201, built.text

    reader = await db_client.get(
        f"/book-releases/{built.json()['id']}/export?format=docx", headers=account.headers
    )
    assert reader.status_code == 200, reader.text

    with zipfile.ZipFile(io.BytesIO(reader.content)) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert media, "рисунок должен попасть в DOCX"
        stored = {hashlib.sha256(archive.read(name)).hexdigest() for name in media}

    drawn = await db_client.get(f"/figure-translations/{row['id']}/image", headers=account.headers)
    assert hashlib.sha256(drawn.content).hexdigest() in stored
    assert hashlib.sha256(picture()).hexdigest() not in stored

    # Формат оригинала: перевод встал на место картинки, остальной архив прежний.
    source = await db_client.get(
        f"/book-releases/{built.json()['id']}/export?format=source", headers=account.headers
    )
    assert source.status_code == 200, source.text

    with zipfile.ZipFile(io.BytesIO(source.content)) as archive:
        assert archive.read("OEBPS/scheme.png") == drawn.content


@requires_database
async def test_roles_and_isolation(
    db_client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_reader(monkeypatch, Reader(GOOD))
    account = await register(db_client)
    _, chapter_id = await figure_chapter(db_client, account)
    row = (await read_figures(db_client, session, account, chapter_id))["images"][0]["current"]

    invited = await invite(db_client, account, role="translator")
    translator = await accept_as_new(db_client, token_of(invited))
    refused = await db_client.post(f"/figure-translations/{row['id']}/approve", headers=translator)
    assert refused.status_code == 403

    stranger = await register(db_client, email="stranger@example.com", organization_name="Чужие")
    for method, path in (
        ("GET", f"/chapters/{chapter_id}/figures"),
        ("POST", f"/chapters/{chapter_id}/figures/translate"),
        ("GET", f"/figure-translations/{row['id']}/image"),
        ("POST", f"/figure-translations/{row['id']}/approve"),
    ):
        response = await db_client.request(method, path, headers=stranger.headers)
        assert response.status_code == 404, path


def test_stub_reader_has_a_name() -> None:
    assert StubFigureReader().name == "stub"
