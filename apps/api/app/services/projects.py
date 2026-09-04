"""Проекты перевода.

Проект — рамка, внутри которой живут документы и терминология. Всё, что
здесь делается, ограничено организацией из контекста: выборки строятся
через `scoped`, а не напрямую.
"""

import uuid

from app.models.organization import Role
from app.models.project import Project
from app.services.base import TenantService
from app.services.errors import NotFoundError
from app.services.slug import slugify

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
