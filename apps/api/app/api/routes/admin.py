"""Управление доступом на площадке.

Все обработчики требуют администратора площадки — это отдельная проверка,
не роль в организации: владелец своего рабочего пространства не должен
решать, кого пускать в чужие.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import SessionDep, SuperuserDep
from app.models.organization import UserStatus
from app.schemas.admin import (
    AdminUserPublic,
    StatusChange,
    UserCounts,
    UserCreate,
    UserCreated,
    UserListPublic,
)
from app.services.admin import AdminService, UserCard

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=UserListPublic)
async def list_users(
    admin: SuperuserDep,
    session: SessionDep,
    status_filter: Annotated[
        UserStatus | None, Query(alias="status", description="Отбор по состоянию доступа")
    ] = None,
    query: Annotated[str | None, Query(description="Часть почты или имени")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserListPublic:
    """Кто зарегистрирован, когда и в каком состоянии.

    Ожидающие решения идут первыми: список открывают ради них.
    """
    service = AdminService(session)
    cards = await service.list_users(status=status_filter, query=query, limit=limit, offset=offset)
    counts = await service.counts()

    return UserListPublic(
        items=[_card(card) for card in cards],
        counts=UserCounts(
            pending=counts[UserStatus.PENDING],
            active=counts[UserStatus.ACTIVE],
            suspended=counts[UserStatus.SUSPENDED],
        ),
    )


@router.patch("/users/{user_id}/status", response_model=AdminUserPublic)
async def change_status(
    user_id: uuid.UUID,
    payload: StatusChange,
    admin: SuperuserDep,
    session: SessionDep,
) -> AdminUserPublic:
    """Открыть или закрыть доступ.

    Закрытие гасит все сессии пользователя: иначе «доступ приостановлен»
    означало бы «приостановлен, когда закончится текущий токен».
    """
    card = await AdminService(session).set_status(user_id, payload.status, by=admin)

    return _card(card)


@router.post("/users", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    admin: SuperuserDep,
    session: SessionDep,
) -> UserCreated:
    """Завести учётную запись с выданным паролем.

    Пароль в ответе — единственный раз за всю его жизнь: в базе лежит
    только хеш. Заведённая администратором запись сразу действующая —
    одобрять собственное решение второй раз незачем.
    """
    created = await AdminService(session).create_user(
        email=payload.email,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        organization_id=payload.organization_id,
        role=payload.role,
        by=admin,
    )

    return UserCreated(
        user=AdminUserPublic(
            id=created.user.id,
            email=created.user.email,
            full_name=created.user.full_name,
            status=created.user.status,
            is_superuser=created.user.is_superuser,
            created_at=created.user.created_at,
            last_login_at=created.user.last_login_at,
            status_changed_at=created.user.status_changed_at,
            status_changed_by=admin.email,
            organizations=[created.organization.name],
        ),
        password=created.password,
        organization_id=created.organization.id,
        organization_name=created.organization.name,
    )


def _card(card: UserCard) -> AdminUserPublic:
    return AdminUserPublic(
        id=card.user.id,
        email=card.user.email,
        full_name=card.user.full_name,
        status=card.user.status,
        is_superuser=card.user.is_superuser,
        created_at=card.user.created_at,
        last_login_at=card.user.last_login_at,
        status_changed_at=card.user.status_changed_at,
        status_changed_by=card.changed_by,
        organizations=card.organizations,
    )
