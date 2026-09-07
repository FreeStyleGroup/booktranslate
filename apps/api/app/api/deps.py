"""Зависимости обработчиков: кто пришёл и в какой организации работает.

Здесь же живёт единственная точка, где HTTP-запрос превращается в
контекст тенанта. Проверять организацию в каждом обработчике вручную —
верный способ однажды забыть и отдать чужие данные.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_access_token
from app.db.session import get_session
from app.models.organization import Membership, User
from app.services.context import RequestContext
from app.services.providers import (
    TermLookupProvider,
    TranslationProvider,
    get_lookup,
    get_provider,
)
from app.services.storage import ObjectStorage, get_storage

# auto_error=False: без заголовка отвечаем своей ошибкой на русском,
# а не стандартным «Not authenticated».
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужен токен доступа",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Токен не принят: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Токен повреждён"
        ) from exc

    user = await session.get(User, user_id)

    # Пользователь мог быть удалён или отключён уже после выдачи токена:
    # подпись всё ещё верна, а пускать его больше нельзя.
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Учётная запись недоступна"
        )

    return user


async def get_context(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    organization_id: Annotated[
        uuid.UUID | None,
        Header(
            alias="X-Organization-Id",
            description="Рабочее пространство; без заголовка берётся единственное доступное",
        ),
    ] = None,
) -> RequestContext:
    """Контекст организации для запроса.

    Организация приходит заголовком, а не из токена: человек работает
    сразу в нескольких и переключается между ними, не выходя из системы.
    Права при этом всегда проверяются по базе — токен говорит, кто пришёл,
    но не что ему сейчас разрешено.
    """
    query = select(Membership).where(Membership.user_id == user.id)
    if organization_id is not None:
        query = query.where(Membership.organization_id == organization_id)

    memberships = list(await session.scalars(query))

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому рабочему пространству",
        )

    if organization_id is None and len(memberships) > 1:
        # Молча выбирать одну из нескольких организаций нельзя: данные
        # уйдут не туда, и заметят это далеко не сразу.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Укажите рабочее пространство в заголовке X-Organization-Id",
        )

    membership = memberships[0]

    return RequestContext(
        user=user,
        organization_id=membership.organization_id,
        role=membership.role,
    )


CurrentUserDep = Annotated[User, Depends(get_current_user)]
ContextDep = Annotated[RequestContext, Depends(get_context)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
ProviderDep = Annotated[TranslationProvider, Depends(get_provider)]
LookupDep = Annotated[TermLookupProvider, Depends(get_lookup)]
