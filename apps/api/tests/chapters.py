"""Книга, доведённая до нужного этапа: так тесты не повторяют весь путь до перевода."""

import asyncio
from dataclasses import dataclass, field

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.worker import once
from tests.factories import Account, create_project

STOP = asyncio.Event()

# Основание пустой версии: без него пустую версию не утвердить.
NO_TERMS = "В этой книге терминов нет: проверено при разборе"


@dataclass(slots=True)
class Prepared:
    book_id: str
    project_id: str
    chapters: list[str] = field(default_factory=list)
    masters: list[str] = field(default_factory=list)

    @property
    def chapter(self) -> str:
        return self.chapters[0]


async def uploaded_book(
    client: AsyncClient,
    account: Account,
    *,
    data: bytes,
    name: str = "manual.txt",
    media: str = "text/plain",
    project_id: str | None = None,
    title: str = "Manual",
) -> Prepared:
    """Книга с основным файлом и утверждёнными границами глав."""
    project = project_id or await create_project(client, account)
    created = await client.post(
        f"/projects/{project}/books", headers=account.headers, json={"title": title}
    )
    assert created.status_code == 201, created.text
    book_id: str = created.json()["id"]

    uploaded = await client.post(
        f"/projects/{project}/documents",
        headers=account.headers,
        files={"file": (name, data, media)},
        data={"book_id": book_id, "source_role": "primary_text"},
    )
    assert uploaded.status_code == 201, uploaded.text

    for step in ("proposal", "approval"):
        response = await client.post(f"/books/{book_id}/chapters/{step}", headers=account.headers)
        assert response.status_code == 200, response.text

    return Prepared(
        book_id=book_id,
        project_id=project,
        chapters=[chapter["id"] for chapter in response.json()["chapters"]],
    )


async def with_masters(client: AsyncClient, account: Account, book: Prepared) -> Prepared:
    """Извлечь и утвердить мастер каждой главы."""
    for chapter_id in book.chapters:
        extracted = await client.post(
            f"/chapters/{chapter_id}/masters", headers=account.headers, json={"reason": None}
        )
        assert extracted.status_code == 201, extracted.text
        master_id = extracted.json()["id"]
        book.masters.append(master_id)

        approved = await client.post(f"/masters/{master_id}/approval", headers=account.headers)
        assert approved.status_code == 200, approved.text

    return book


async def decide_terms(
    client: AsyncClient, account: Account, chapter_id: str, accepted: dict[str, str] | None = None
) -> None:
    """Собрать кандидатов главы и решить всех: названные принять, остальные отклонить."""
    wanted = {source.casefold(): target for source, target in (accepted or {}).items()}

    found = await client.post(
        f"/chapters/{chapter_id}/terminology/extract", headers=account.headers
    )
    assert found.status_code == 200, found.text

    def decision(item: dict) -> dict:
        key = item["source_term"].casefold()

        if key in wanted:
            return {"candidate_id": item["id"], "accept": True, "target_term": wanted[key]}

        return {"candidate_id": item["id"], "accept": False}

    decisions = [decision(item) for item in found.json() if item["status"] == "new"]

    if decisions:
        decided = await client.post(
            f"/chapters/{chapter_id}/terminology/decisions",
            headers=account.headers,
            json={"decisions": decisions},
        )
        assert decided.status_code == 200, decided.text


async def approve_glossary(client: AsyncClient, account: Account, book_id: str) -> dict:
    """Собрать и утвердить версию глоссария книги."""
    drafted = await client.post(
        f"/books/{book_id}/glossary-versions", headers=account.headers, json={"chapter_id": None}
    )
    assert drafted.status_code == 201, drafted.text
    version = drafted.json()

    approved = await client.post(
        f"/glossary-versions/{version['id']}/approval",
        headers=account.headers,
        json={"empty_reason": NO_TERMS if version["term_count"] == 0 else None},
    )
    assert approved.status_code == 200, approved.text

    result: dict = approved.json()
    return result


async def open_book(
    client: AsyncClient,
    account: Account,
    *,
    data: bytes,
    name: str = "manual.txt",
    media: str = "text/plain",
    accepted: dict[str, str] | None = None,
    project_id: str | None = None,
    title: str = "Manual",
) -> Prepared:
    """Книга, главы которой уже можно переводить."""
    book = await uploaded_book(
        client, account, data=data, name=name, media=media, project_id=project_id, title=title
    )
    await with_masters(client, account, book)

    for chapter_id in book.chapters:
        await decide_terms(client, account, chapter_id, accepted)

    await approve_glossary(client, account, book.book_id)

    return book


async def translate(
    client: AsyncClient, session: AsyncSession, account: Account, chapter_id: str
) -> dict:
    """Поставить главу в очередь и выполнить задание рабочим."""
    started = await client.post(
        f"/chapters/{chapter_id}/translation", headers=account.headers, json={}
    )
    assert started.status_code == 201, started.text
    assert await once(session, "test", STOP) is True

    state = await client.get(f"/chapters/{chapter_id}/translation", headers=account.headers)
    assert state.status_code == 200, state.text

    body: dict = state.json()
    return body


async def translated_book(
    client: AsyncClient,
    session: AsyncSession,
    account: Account,
    *,
    data: bytes,
    name: str = "manual.txt",
    media: str = "text/plain",
    accepted: dict[str, str] | None = None,
    project_id: str | None = None,
    title: str = "Manual",
) -> Prepared:
    """Книга, переведённая целиком."""
    book = await open_book(
        client,
        account,
        data=data,
        name=name,
        media=media,
        accepted=accepted,
        project_id=project_id,
        title=title,
    )

    for chapter_id in book.chapters:
        await translate(client, session, account, chapter_id)

    return book


async def block_rows(client: AsyncClient, account: Account, chapter_id: str) -> list[dict]:
    response = await client.get(
        f"/chapters/{chapter_id}/translation/blocks?limit=200", headers=account.headers
    )
    assert response.status_code == 200, response.text

    items: list[dict] = response.json()["items"]
    return items
