"""Проекты перевода.

Проект — рамка, внутри которой живут документы и терминология. Всё, что
здесь делается, ограничено организацией из контекста: выборки строятся
через `scoped`, а не напрямую.
"""

import uuid

from sqlalchemy import select

from app.models.document import Document
from app.models.job import LIVE, TranslationJob
from app.models.organization import Role
from app.models.project import Project
from app.services.base import TenantService
from app.services.errors import ConflictError, NotFoundError
from app.services.slug import slugify
from app.services.storage import ObjectStorage

# Кто заводит и меняет проекты. Переводчик и редактор работают внутри
# готового проекта, но не создают их: это решение о деньгах и сроках.
MANAGING_ROLES = (Role.ADMIN, Role.MANAGER)


class ProjectService(TenantService):
    async def create(
        self,
        *,
        name: str,
        source_language: str,
        target_language: str,
        description: str | None = None,
        slug: str | None = None,
    ) -> Project:
        self._context.require(*MANAGING_ROLES)

        project = Project(
            organization_id=self.organization_id,
            name=name,
            slug=await self._free_slug(slug or slugify(name, fallback="project")),
            description=description,
            source_language=source_language,
            target_language=target_language,
        )

        self._session.add(project)
        await self._session.commit()
        await self._session.refresh(project)

        return project

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Project]:
        query = self.scoped(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)

        return list(await self._session.scalars(query))

    async def get(self, project_id: uuid.UUID) -> Project:
        """Проект своей организации.

        Чужой проект отдаётся как отсутствующий, а не как запрещённый:
        «403» подтвердил бы, что такой идентификатор существует.
        """
        project = await self._session.scalar(self.scoped(Project).where(Project.id == project_id))

        if project is None:
            raise NotFoundError("Проект не найден")

        return project

    async def delete(self, project_id: uuid.UUID, *, storage: ObjectStorage) -> None:
        """Удалить проект вместе с книгами, их сегментами и терминами.

        Записи уходят каскадом базы одной транзакцией: книги, сегменты,
        задания, термины проекта, записи о загрузках словарей. Файлы книг
        в хранилище каскад не видит — их ключи собираются заранее и
        удаляются после записи, в том же порядке, что и у одной книги:
        упасть между ними значит оставить файл без записи, который
        подберёт уборка, а не запись без файла.

        Проект с книгой в очереди на перевод не удаляется: рабочий держит
        задание и пишет в сегменты, которых через секунду не будет.
        Остановить перевод — отдельное осознанное действие.
        """
        self._context.require(*MANAGING_ROLES)

        project = await self.get(project_id)

        live = await self._session.scalar(
            select(TranslationJob.id)
            .join(Document, Document.id == TranslationJob.document_id)
            .where(
                Document.organization_id == self.organization_id,
                Document.project_id == project.id,
                TranslationJob.state.in_(list(LIVE)),
            )
            .limit(1)
        )
        if live is not None:
            raise ConflictError(
                "В проекте идёт перевод: остановите задание на карточке книги, потом удаляйте"
            )

        storage_keys = list(
            await self._session.scalars(
                self.scoped(Document)
                .where(Document.project_id == project.id)
                .with_only_columns(Document.storage_key)
            )
        )

        await self._session.delete(project)
        await self._session.commit()

        for storage_key in storage_keys:
            await storage.delete(storage_key)

    async def _free_slug(self, base: str) -> str:
        """Свободное короткое имя внутри организации.

        Уникальность стережёт ограничение в базе; здесь — попытка выбрать
        читаемое имя, а не сразу вешать случайный суффикс.
        """
        candidate = base
        suffix = 2

        while await self._session.scalar(
            self.scoped(Project).where(Project.slug == candidate).limit(1)
        ):
            candidate = f"{base}-{suffix}"
            suffix += 1

        return candidate
