"""Заготовки для тестов: зарегистрированный пользователь и его проект.

Каждый тест идёт в транзакции, которая откатывается, поэтому одинаковые
почты в разных тестах не конфликтуют и специально разводить их не нужно.
"""

import io
import uuid
import zipfile
from dataclasses import dataclass

from httpx import AsyncClient

from tests.conftest import ROOT_EMAIL, ROOT_PASSWORD

PASSWORD = "correct-horse-battery"


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


async def admin_headers(client: AsyncClient) -> dict[str, str]:
    """Заголовки администратора площадки."""
    response = await client.post(
        "/auth/login", json={"email": ROOT_EMAIL, "password": ROOT_PASSWORD}
    )
    assert response.status_code == 200, response.text

    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def find_user(client: AsyncClient, email: str) -> str:
    """Найти заявку по почте глазами администратора.

    Регистрация номера записи не возвращает — ответ одинаков для свободной
    и занятой почты, иначе форма подсказывала бы, кто здесь зарегистрирован.
    Значит, одобрять заявку надо так же, как это делает живой
    администратор: найдя её в списке.
    """
    response = await client.get(
        "/admin/users", params={"query": email}, headers=await admin_headers(client)
    )
    assert response.status_code == 200, response.text

    items = [item for item in response.json()["items"] if item["email"] == email]
    assert len(items) == 1, response.text

    user_id: str = items[0]["id"]
    return user_id


async def register(
    client: AsyncClient,
    *,
    email: str = "owner@example.com",
    organization_name: str = "Бюро переводов",
) -> Account:
    """Зарегистрировать пользователя и открыть ему доступ.

    Регистрация — только заявка, поэтому здесь же её одобряет администратор
    площадки: тестам почти всегда нужен работающий пользователь, а не
    ожидающий решения. Сам порядок «заявка — одобрение — вход» при этом
    проходится по-настоящему, а не обходится записью в базу.
    """
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": "Владелец",
            "organization_name": organization_name,
        },
    )
    assert response.status_code == 202, response.text
    user_id = await find_user(client, email)

    approved = await client.patch(
        f"/admin/users/{user_id}/status",
        headers=await admin_headers(client),
        json={"status": "active"},
    )
    assert approved.status_code == 200, approved.text

    entered = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert entered.status_code == 200, entered.text

    headers = {"Authorization": f"Bearer {entered.json()['access_token']}"}

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


@dataclass(frozen=True, slots=True)
class PdfLine:
    """Строка на странице PDF: текст и кегль."""

    text: str
    size: int = 12
    # Интервал до следующей строки в кеглях. Чуть больше единицы — строки
    # одного блока; почти два — pdfminer видит в каждой строке свой блок,
    # как в плотно свёрстанных каталогах.
    leading: float = 1.3


@dataclass(frozen=True, slots=True)
class PdfPage:
    """Страница PDF: строки сверху вниз и, если нужно, картинка вместо текста."""

    lines: tuple[PdfLine, ...] = ()
    image: bool = False


def pdf_bytes(pages: list[PdfPage]) -> bytes:
    """Настоящий PDF, собранный руками: страницы, строки Helvetica, картинка.

    Библиотеки, пишущей PDF, в проекте нет и ради тестов она не нужна: PDF
    из одного шрифта и строк с координатами укладывается в сотню байт
    объектов, а таблица ссылок считается тут же. Строки идут сверху вниз
    с интервалом в полтора кегля — так pdfminer собирает их в блоки, как в
    настоящей книге. Пустая строка — просвет между блоками.

    Латиница только: Helvetica без вложенного шрифта кириллицу не
    кодирует, а тест проверяет разбор, а не шрифты.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def escape(text: str) -> bytes:
        return (
            text.encode("latin-1")
            .replace(b"\\", b"\\\\")
            .replace(b"(", b"\\(")
            .replace(b")", b"\\)")
        )

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 1 >>\nstream\n\xff\nendstream"
    )
    pages_id = len(objects) + 1 + 2 * len(pages)
    page_ids: list[int] = []

    for page in pages:
        parts: list[bytes] = []
        y = 780

        for line in page.lines:
            if line.text:
                parts.append(
                    b"BT /F1 "
                    + str(line.size).encode()
                    + b" Tf 72 "
                    + str(y).encode()
                    + b" Td ("
                    + escape(line.text)
                    + b") Tj ET"
                )
            y -= int(line.size * line.leading)

        if page.image:
            parts.append(b"q 200 0 0 200 72 400 cm /Im1 Do Q")

        content = b"\n".join(parts)
        stream = add(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        page_ids.append(
            add(
                b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R "
                b"/MediaBox [0 0 595 842] /Resources << /Font << /F1 "
                + str(font).encode()
                + b" 0 R >> /XObject << /Im1 "
                + str(image).encode()
                + b" 0 R >> >> "
                b"/Contents " + str(stream).encode() + b" 0 R >>"
            )
        )

    kids = b" ".join(str(number).encode() + b" 0 R" for number in page_ids)
    real_pages = add(
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode() + b" >>"
    )
    assert real_pages == pages_id
    catalog = add(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []

    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root "
        + str(catalog).encode()
        + b" 0 R >>\nstartxref\n"
        + str(xref).encode()
        + b"\n%%EOF\n"
    )

    return bytes(out)


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
