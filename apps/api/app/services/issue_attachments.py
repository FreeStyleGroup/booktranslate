"""Вложения к замечаниям: снимки страниц и формул.

Принимается только то, что можно честно назвать снимком. Тип определяется по первым байтам
файла, а не по имени и не со слов браузера; SVG не принимается вовсе: это разметка, и в ней
может быть сценарий. Имя файла только показывается, ключ хранилища строится из идентификатора.
"""

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.issue import IssueAttachment
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.documents import spool
from app.services.errors import ConflictError, UnsupportedFormatError
from app.services.issues import REGISTERING_ROLES, IssueService
from app.services.storage import ObjectStorage

ATTACHMENT_LIMIT = 10 * 1024 * 1024
CHUNK = 256 * 1024
NAME_MAX = 255

_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")


def sniff(head: bytes) -> tuple[str, str] | None:
    """Тип и расширение по началу файла. `None` — такое не принимаем."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"

    return None


def clean_name(name: str | None, fallback: str) -> str:
    """Имя для показа: без пути и управляющих знаков. Для хранилища оно не используется."""
    last = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    safe = _UNSAFE_NAME.sub("", last).strip()

    return safe[:NAME_MAX] or fallback


class IssueAttachments(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage
        self._issues = IssueService(session, context, storage)

    async def accept(
        self, issue_id: uuid.UUID, *, file: UploadFile, filename: str | None
    ) -> IssueAttachment:
        self._context.require(*REGISTERING_ROLES)

        issue = await self._issues.get(issue_id)
        if issue.archived_at is not None:
            raise ConflictError("Замечание в архиве: сначала верните его")

        upload = await spool(_chunks(file), limit_bytes=ATTACHMENT_LIMIT)

        try:
            kind = sniff(_head(upload.path))
            if kind is None:
                raise UnsupportedFormatError("Принимаются снимки PNG, JPEG, WebP и файлы PDF")

            media_type, extension = kind
            attachment_id = uuid.uuid4()
            # Ключ содержит организацию, как и у документов: удаление клиента сводится к
            # удалению каталога. Имя объекта — идентификатор, а не то, что прислал человек.
            key = f"{self.organization_id}/issues/{issue.id}/{attachment_id}{extension}"
            await self._storage.put(key, upload.path)
        finally:
            upload.discard()

        return await self._issues.record_attachment(
            IssueAttachment(
                id=attachment_id,
                organization_id=self.organization_id,
                issue_id=issue.id,
                storage_key=key,
                filename=clean_name(filename, f"снимок{extension}"),
                media_type=media_type,
                size_bytes=upload.size,
                content_hash=upload.content_hash,
                uploaded_by_id=self._context.user.id,
            )
        )

    async def get(self, issue_id: uuid.UUID, attachment_id: uuid.UUID) -> IssueAttachment:
        return await self._issues.attachment(issue_id, attachment_id)

    def stream(self, attachment: IssueAttachment) -> AsyncIterator[bytes]:
        return self._storage.stream(attachment.storage_key)


def _head(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(16)


async def _chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await file.read(CHUNK):
        yield chunk
