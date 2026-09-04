"""Общее основание сервисов, работающих с данными организации.

Здесь единственное место, где мультитенантность превращается из намерения
в код: выборка строится методом `scoped`, который сам добавляет условие по
организации. Голый `select(Document)` в сервисе — это ошибка, которую
заметят, только когда клиент увидит чужой документ.
"""

import uuid
from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mixins import TenantMixin
from app.services.context import RequestContext

TenantModel = TypeVar("TenantModel", bound=TenantMixin)


class TenantService:
    def __init__(self, session: AsyncSession, context: RequestContext) -> None:
        self._session = session
        self._context = context

    @property
    def organization_id(self) -> uuid.UUID:
        return self._context.organization_id

    def scoped(self, model: type[TenantModel]) -> Select[tuple[TenantModel]]:
        """Выборка, ограниченная организацией из контекста."""
        return select(model).where(model.organization_id == self._context.organization_id)
