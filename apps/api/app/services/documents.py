"""Приём документов.

Файл принимается в три шага: сначала он целиком укладывается во временный
файл (с подсчётом размера и контрольной суммы на лету), затем по готовому
файлу определяется формат, и только потом заводится запись и объект в
хранилище. Порядок именно такой:

* размер проверяется по мере чтения — узнавать о превышении, когда гигабайт
  уже принят, поздно;
* формат определяется по содержимому, а контейнерам (DOCX, EPUB) для этого
  нужен файл целиком, а не первые байты;
* объект кладётся в хранилище до фиксации записи — запись, ссылающаяся на
  несуществующий файл, хуже, чем файл без записи: первое ломает интерфейс,
  второе видно уборщику мусора.
"""

import asyncio
import hashlib
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document, DocumentStatus, SourceFormat
from app.models.organization import Role
from app.services.base import TenantService
from app.services.context import RequestContext
from app.services.errors import (
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedFormatError,
)
from app.services.formats import detect_format, extension
from app.services.projects import ProjectService
from app.services.storage import ObjectStorage

# Загружать документы вправе и переводчик: приносить исходники — часть его
# работы. Смотреть и редактировать может кто угодно из участников.
UPLOADING_ROLES = (Role.ADMIN, Role.MANAGER, Role.TRANSLATOR)
DELETING_ROLES = (Role.ADMIN, Role.MANAGER)


class SpooledUpload:
    """Принятый во временный файл поток с посчитанными размером и суммой."""

    def __init__(self, path: Path, size: int, content_hash: str) -> None:
        self.path = path
        self.size = size
        self.content_hash = content_hash

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


async def spool(stream: AsyncIterator[bytes], *, limit_bytes: int) -> SpooledUpload:
    """Принять поток во временный файл, считая размер и контрольную сумму.

    Сумма считается здесь же, одним проходом: отдельное чтение файла ради
    неё удвоило бы дисковый ввод-вывод на каждой загрузке.
    """
    digest = hashlib.sha256()
    size = 0

    # mkstemp, а не NamedTemporaryFile: файл должен пережить закрытие
    # дескриптора — дальше его читает определитель формата и забирает
    # хранилище.
    descriptor, name = tempfile.mkstemp(prefix="booktranslate-", suffix=".upload")
    path = Path(name)

    try:
        with os.fdopen(descriptor, "wb") as handle:
            async for chunk in stream:
                size += len(chunk)
                if size > limit_bytes:
                    raise PayloadTooLargeError(
                        f"Файл больше разрешённых {limit_bytes // (1024 * 1024)} МБ"
                    )

                digest.update(chunk)
                # Запись на диск блокирует поток событий, поэтому уходит в
                # отдельный: пока идёт запись мегабайта, сервер обслуживает
                # остальные запросы.
                await asyncio.to_thread(handle.write, chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    return SpooledUpload(path=path, size=size, content_hash=digest.hexdigest())


class DocumentService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def upload(
        self,
        *,
        project_id: uuid.UUID,
        filename: str,
        stream: AsyncIterator[bytes],
        title: str | None = None,
    ) -> tuple[Document, bool]:
        """Принять файл в проект.

        Возвращает документ и признак того, что он заведён именно сейчас:
        повторная загрузка того же файла отдаёт существующий документ, а не
        плодит копию и не запускает разбор во второй раз.
        """
        self._context.require(*UPLOADING_ROLES)

        project = await ProjectService(self._session, self._context).get(project_id)
        safe_name = Path(filename).name[:255] or "document"

        upload = await spool(stream, limit_bytes=get_settings().max_upload_bytes)

        try:
            if upload.size == 0:
                raise InvalidInputError("Файл пуст")

            source_format = await asyncio.to_thread(detect_format, upload.path, safe_name)
            if source_format is None:
                raise UnsupportedFormatError(
                    "Формат файла не поддерживается: принимаются PDF, DOCX, EPUB, "
                    "HTML, Markdown, XLIFF и обычный текст"
                )

            existing = await self._find_by_hash(project_id, upload.content_hash)
            if existing is not None:
                return existing, False

            document = await self._store(
                project_id=project.id,
                title=title or Path(safe_name).stem or safe_name,
                original_filename=safe_name,
                source_format=source_format,
                upload=upload,
            )
        finally:
            # Временный файл переезжает в хранилище методом move, поэтому в
            # успешном случае удалять уже нечего. Во всех остальных — есть.
            upload.discard()

        return document, True

    async def list(
        self, *, project_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[Document]:
        # Проект запрашивается, чтобы отличить «в проекте нет документов» от
        # «такого проекта нет»: пустой список на чужой проект молча скрыл бы
        # ошибку в адресе.
        await ProjectService(self._session, self._context).get(project_id)

        query = (
            self.scoped(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return list(await self._session.scalars(query))

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self._session.scalar(
            self.scoped(Document).where(Document.id == document_id)
        )

        if document is None:
            raise NotFoundError("Документ не найден")

        return document

    def stream(self, document: Document) -> AsyncIterator[bytes]:
        """Содержимое исходного файла кусками."""
        return self._storage.stream(document.storage_key)

    async def delete(self, document_id: uuid.UUID) -> None:
        self._context.require(*DELETING_ROLES)

        document = await self.get(document_id)
        storage_key = document.storage_key

        await self._session.delete(document)
        await self._session.commit()

        # Файл удаляется после записи: если упасть между ними, останется
        # объект без документа — его подберёт уборка. Обратный порядок
        # оставил бы документ, который нельзя открыть.
        await self._storage.delete(storage_key)

    async def _find_by_hash(self, project_id: uuid.UUID, content_hash: str) -> Document | None:
        document: Document | None = await self._session.scalar(
            self.scoped(Document).where(
                Document.project_id == project_id,
                Document.content_hash == content_hash,
            )
        )

        return document

    async def _store(
        self,
        *,
        project_id: uuid.UUID,
        title: str,
        original_filename: str,
        source_format: SourceFormat,
        upload: SpooledUpload,
    ) -> Document:
        # Идентификатор задаётся явно, а не значением по умолчанию у
        # колонки: то присваивается при вставке, а ключ хранилища нужен
        # раньше — он строится из идентификатора и пишется в ту же строку.
        document_id = uuid.uuid4()
        # Ключ содержит организацию: при разборе инцидента видно, чьи это
        # данные, а удаление клиента сводится к удалению одного поддерева.
        # Имя объекта — идентификатор документа, а не имя файла: имя
        # приходит от человека и требовало бы очистки.
        storage_key = f"{self.organization_id}/{project_id}/{document_id}{extension(source_format)}"

        document = Document(
            id=document_id,
            organization_id=self.organization_id,
            project_id=project_id,
            title=title[:500],
            original_filename=original_filename,
            source_format=source_format,
            status=DocumentStatus.UPLOADED,
            storage_key=storage_key,
            size_bytes=upload.size,
            content_hash=upload.content_hash,
        )

        self._session.add(document)

        try:
            await self._session.flush()
        except IntegrityError:
            # Тот же файл загрузили дважды одновременно: проверка по сумме
            # прошла в обоих запросах, а уникальный индекс пропустил один.
            # Проигравший отдаёт документ победителя.
            await self._session.rollback()
            existing = await self._find_by_hash(project_id, upload.content_hash)
            if existing is None:
                raise

            return existing

        await self._storage.put(document.storage_key, upload.path)

        try:
            await self._session.commit()
        except BaseException:
            # Запись не состоялась — файл в хранилище больше не на что
            # ссылаться, убираем сразу, а не оставляем уборщику.
            await self._storage.delete(document.storage_key)
            raise

        await self._session.refresh(document)

        return document
