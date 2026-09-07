"""Заготовки для тестов: зарегистрированный пользователь и его проект.

Каждый тест идёт в транзакции, которая откатывается, поэтому одинаковые
почты в разных тестах не конфликтуют и специально разводить их не нужно.
"""

import io
import uuid
import zipfile

from httpx import AsyncClient


class Account:
    """Зарегистрированный пользователь: заголовки, он сам и его организация."""

    def __init__(
        self, headers: dict[str, str], user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        self.headers = headers
        self.user_id = user_id
        self.organization_id = organization_id

    def headers_for(self, organization_id: uuid.UUID) -> dict[str, str]:
        """Заголовки для работы в указанной организации."""
        return {**self.headers, "X-Organization-Id": str(organization_id)}


async def register(
    client: AsyncClient,
    *,
    email: str = "owner@example.com",
    organization_name: str = "Бюро переводов",
) -> Account:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery",
            "full_name": "Владелец",
            "organization_name": organization_name,
        },
    )
    assert response.status_code == 201, response.text

    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()

    return Account(
        headers=headers,
        user_id=uuid.UUID(body["user"]["id"]),
        organization_id=uuid.UUID(body["memberships"][0]["organization_id"]),
    )


async def create_project(
    client: AsyncClient, account: Account, *, name: str = "Руководство по эксплуатации"
) -> str:
    response = await client.post(
        "/projects",
        headers=account.headers,
        json={"name": name, "source_language": "en", "target_language": "ru"},
    )
    assert response.status_code == 201, response.text

    project_id: str = response.json()["id"]
    return project_id


def real_docx_bytes() -> bytes:
    """Настоящий DOCX со всеми обязательными частями.

    Отличается от `docx_bytes` назначением: та подделка годится только для
    определения формата, а разбору нужен документ, который открывается
    библиотекой. Собирается самой python-docx — тогда тест проверяет разбор,
    а не умение автора теста воспроизвести формат Word.
    """
    import docx

    document = docx.Document()
    document.add_heading("Глава первая", level=1)
    document.add_paragraph("Первый абзац главы.")
    document.add_paragraph("Пункт списка", style="List Bullet")

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Параметр"
    table.cell(0, 1).text = "Значение"

    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()


def epub_bytes(chapters: list[tuple[str, str]] | None = None) -> bytes:
    """Минимальный EPUB: контейнер, опись и главы.

    Имена файлов глав намеренно не совпадают с порядком чтения по алфавиту —
    так тест ловит разбор, который сортирует главы по имени вместо описи.
    """
    chapters = chapters or [
        ("part0010.xhtml", "<h1>Вторая глава</h1><p>Текст второй главы.</p>"),
        ("part0002.xhtml", "<h1>Первая глава</h1><p>Текст первой главы.</p>"),
    ]

    manifest = "".join(
        f'<item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, (name, _) in enumerate(chapters)
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf"'
            ' media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>",
        )

        for name, body in chapters:
            archive.writestr(
                f"OEBPS/{name}",
                f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                f"<body>{body}</body></html>",
            )

    return buffer.getvalue()


def docx_bytes(text: str = "Раздел первый") -> bytes:
    """Минимальный DOCX: ZIP с обязательной частью `word/document.xml`.

    Настоящий Word кладёт туда куда больше, но определение формата смотрит
    именно на эту часть, и подделывать остальное ради теста незачем.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<document><p>{text}</p></document>")

    return buffer.getvalue()
