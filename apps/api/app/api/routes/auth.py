"""Вход, регистрация, обновление доступа.

Обработчики тонкие: разбирают запрос и зовут сервис. Логика — в
`app/services/auth.py`, перевод ошибок предметной области в коды ответа —
в `app/api/errors.py`.
"""

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUserDep, SessionDep
from app.models.organization import Membership, Organization
from app.schemas.auth import (
    AccessRequestPublic,
    CurrentUser,
    LoginRequest,
    MembershipPublic,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserPublic,
)
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_info(request: Request) -> tuple[str | None, str | None]:
    """Кто и откуда — для списка сессий пользователя.

    Адрес берётся из соединения, а не из X-Forwarded-For: заголовок
    подделывается кем угодно, а за обратным прокси его подставляет сам
    прокси, и учитывать это будет задача развёртывания.
    """
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    return user_agent, ip_address


@router.post("/register", response_model=AccessRequestPublic, status_code=status.HTTP_202_ACCEPTED)
async def register(payload: RegisterRequest, session: SessionDep) -> AccessRequestPublic:
    """Подать заявку на доступ.

    202, а не 201: учётная запись создана, но внутрь не пускает — доступ
    открывает администратор. Токенов в ответе нет намеренно, иначе
    одобрение оказалось бы формальностью, которую можно обойти, просто не
    перезагрузив страницу.

    Ответ один и тот же независимо от того, была ли почта свободна: иначе
    форма регистрации отвечала бы на вопрос «а работает ли здесь такой-то»,
    который вход отвечать отказывается.
    """
    await AuthService(session).register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
    )

    return AccessRequestPublic()


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, session: SessionDep) -> TokenPair:
    user_agent, ip_address = _client_info(request)

    return await AuthService(session).login(
        email=payload.email,
        password=payload.password,
        user_agent=user_agent,
        ip_address=ip_address,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, request: Request, session: SessionDep) -> TokenPair:
    user_agent, ip_address = _client_info(request)

    return await AuthService(session).refresh(
        refresh_token=payload.refresh_token,
        user_agent=user_agent,
        ip_address=ip_address,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, session: SessionDep) -> Response:
    await AuthService(session).logout(refresh_token=payload.refresh_token)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=CurrentUser)
async def me(user: CurrentUserDep, session: SessionDep) -> CurrentUser:
    rows = await session.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    )

    memberships: list[MembershipPublic] = [
        MembershipPublic(
            organization_id=organization.id,
            organization_name=organization.name,
            role=membership.role,
        )
        for membership, organization in rows.all()
    ]

    return CurrentUser(user=UserPublic.model_validate(user), memberships=memberships)
