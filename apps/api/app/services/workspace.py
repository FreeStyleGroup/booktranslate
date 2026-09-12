"""Настройки рабочего пространства: чем переводить и чем делиться.

Модель выбирается пространством, а не площадкой, потому что цена решения
принадлежит заказчику: студенту с дипломом нужна дешёвая и быстрая, бюро с
серией руководств — самая точная. Одно умолчание на всех заставляло бы
одних переплачивать, а других терпеть ошибки.

Тематика и разрешение на общий словарь — тоже решения пространства
целиком: первая открывает подсказки из общего словаря площадки, второе
отдаёт площадке термины загруженных словарей.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Role
from app.models.workspace import WorkspaceSettings
from app.services.base import TenantService
from app.services.errors import InvalidInputError
from app.services.models import default_model, is_available
from app.services.subjects import is_subject

# Смена модели меняет и счёт, и качество всех следующих книг; разрешение
# на общий словарь отдаёт данные наружу. Это распоряжение деньгами и
# данными пространства, а не работа с текстом.
SETTINGS_ROLES = (Role.ADMIN,)

UPDATABLE_FIELDS = frozenset({"translation_model", "subject", "share_glossary"})


async def model_for(session: AsyncSession, organization_id: uuid.UUID) -> str:
    """Модель, которой переводит это пространство.

    Без контекста запроса: спрашивает и фоновый рабочий, у которого
    запроса нет, а организация известна по заданию.
    """
    chosen = await session.scalar(
        select(WorkspaceSettings.translation_model).where(
            WorkspaceSettings.organization_id == organization_id
        )
    )

    return chosen or default_model()


async def subject_for(session: AsyncSession, organization_id: uuid.UUID) -> str | None:
    """Тематика пространства; пусто — подсказок из общего словаря нет."""
    return await session.scalar(
        select(WorkspaceSettings.subject).where(
            WorkspaceSettings.organization_id == organization_id
        )
    )


class WorkspaceSettingsService(TenantService):
    async def load(self) -> WorkspaceSettings | None:
        settings: WorkspaceSettings | None = await self._session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.organization_id == self.organization_id
            )
        )

        return settings

    async def model(self) -> str:
        return await model_for(self._session, self.organization_id)

    async def save(self, **changes: Any) -> WorkspaceSettings:
        """Записать присланное. Меняется только то, что прислали.

        Модель обязана быть из каталога: имя, набранное с опечаткой, ушло
        бы в запрос и вернулось бы отказом посреди книги, а виноватым
        выглядел бы ключ. Пусто — вернуться к умолчанию площадки. Тематика
        — из списка по той же причине; пусто — без тематики.
        """
        self._context.require(*SETTINGS_ROLES)

        unknown = set(changes) - UPDATABLE_FIELDS
        if unknown:
            raise InvalidInputError("Нельзя менять поля: " + ", ".join(sorted(unknown)))

        model = changes.get("translation_model")
        if model is not None and not is_available(model):
            raise InvalidInputError(f"Модели «{model}» нет в каталоге")

        subject = changes.get("subject")
        if subject is not None and not is_subject(subject):
            raise InvalidInputError(f"Тематики «{subject}» нет в списке")

        settings = await self._ensure()

        for name, value in changes.items():
            setattr(settings, name, value)

        await self._session.commit()
        await self._session.refresh(settings)

        return settings

    async def _ensure(self) -> WorkspaceSettings:
        settings = await self.load()

        if settings is None:
            settings = WorkspaceSettings(organization_id=self.organization_id)
            self._session.add(settings)

        return settings
