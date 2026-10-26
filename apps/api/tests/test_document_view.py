"""Просмотр исходника в браузере — только PDF."""

from httpx import AsyncClient

from tests.conftest import requires_database
from tests.factories import PdfLine, PdfPage, create_project, pdf_bytes, register


@requires_database
async def test_pdf_opens_for_viewing(db_client: AsyncClient) -> None:
    """Визуальный эталон открывается во вкладке — со страницей, а не скачиванием."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={
            "file": (
                "print.pdf",
                pdf_bytes([PdfPage(lines=(PdfLine("Page."),))]),
                "application/pdf",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text

    response = await db_client.get(
        f"/documents/{uploaded.json()['id']}/content",
        params={"view": "true"},
        headers=account.headers,
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"


@requires_database
async def test_html_is_never_opened_for_viewing(db_client: AsyncClient) -> None:
    """HTML заказчика, открытый с домена сервиса, выполнил бы свои скрипты от его имени."""
    account = await register(db_client)
    project_id = await create_project(db_client, account)
    uploaded = await db_client.post(
        f"/projects/{project_id}/documents",
        headers=account.headers,
        files={"file": ("page.html", b"<p>Text.</p><script>alert(1)</script>", "text/html")},
    )

    viewed = await db_client.get(
        f"/documents/{uploaded.json()['id']}/content",
        params={"view": "true"},
        headers=account.headers,
    )
    downloaded = await db_client.get(
        f"/documents/{uploaded.json()['id']}/content", headers=account.headers
    )

    assert viewed.status_code == 400
    assert downloaded.headers["content-disposition"].startswith("attachment;")
