"""Команда рабочего пространства и приглашения в него.

Управление командой — внутри пространства и требует его контекста.
Принятие приглашения — снаружи: у того, кто идёт по ссылке, ещё нет ни
организации, ни, возможно, учётной записи, поэтому эти две ручки живут
под `/auth` — рядом со входом и с тем же ограничителем частоты.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from app.api.deps import ContextDep, OptionalUserDep, SessionDep
from app.core.config import get_settings
from app.models.organization import Membership
from app.models.team import Invitation
from app.schemas.team import (
    AcceptedPublic,
    InvitationAccept,
    InvitationLookup,
    InvitationPreview,
    InvitationPublic,
    InvitedPublic,
    InviteRequest,
    MemberPublic,
    RoleChange,
    TeamPublic,
)
from app.services.team import InvitationService, TeamService

router = APIRouter(tags=["team"])


def _member(membership: Membership) -> MemberPublic:
    return MemberPublic(
        user_id=membership.user_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        last_login_at=membership.user.last_login_at,
        joined_at=membership.created_at,
    )


def _invitation(invitation: Invitation) -> InvitationPublic:
    inviter = invitation.invited_by

    return InvitationPublic(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        invited_by=None if inviter is None else (inviter.full_name or inviter.email),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        expired=invitation.expires_at <= datetime.now(UTC),
    )


@router.get("/team", response_model=TeamPublic)
async def team(context: ContextDep, session: SessionDep) -> TeamPublic:
    """Кто в команде и кого ждут.

    Видят все участники: команда — не секрет от самой себя. Управлять
    составом могут владелец и администратор; витрина узнаёт об этом по
    роли смотрящего в ответе.
    """
    service = TeamService(session, context)

    return TeamPublic(
        members=[_member(row) for row in await service.members()],
        invitations=[_invitation(row) for row in await service.invitations()],
        my_role=context.role,
    )


@router.post("/team/invitations", response_model=InvitedPublic, status_code=status.HTTP_201_CREATED)
async def invite(payload: InviteRequest, context: ContextDep, session: SessionDep) -> InvitedPublic:
    """Пригласить по почте.

    Ссылка в ответе показывается один раз: если письмо не ушло — почта
    площадки не настроена или сервер отказал, — её передают сами. Факт и
    причина отправки — рядом, а не додумываются.
    """
    invited = await TeamService(session, context).invite(
        email=payload.email, role=payload.role, web_url=get_settings().web_url
    )

    return InvitedPublic(
        invitation=_invitation(invited.invitation),
        link=invited.link,
        email_sent=invited.delivery.sent,
        email_detail=invited.delivery.detail,
    )


@router.delete("/team/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(invitation_id: uuid.UUID, context: ContextDep, session: SessionDep) -> Response:
    await TeamService(session, context).revoke(invitation_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/team/members/{user_id}", response_model=MemberPublic)
async def change_role(
    user_id: uuid.UUID, payload: RoleChange, context: ContextDep, session: SessionDep
) -> MemberPublic:
    """Сменить роль. Владельца назначает и снимает только владелец; свою
    роль не меняют — иначе единственный владелец мог бы оставить
    пространство без хозяина."""
    return _member(await TeamService(session, context).change_role(user_id, payload.role))


@router.delete("/team/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(user_id: uuid.UUID, context: ContextDep, session: SessionDep) -> Response:
    """Убрать из команды. Учётная запись остаётся: у человека могут быть
    другие пространства, а закрыть доступ на площадку может только её
    администратор."""
    await TeamService(session, context).remove(user_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/invitations/lookup", response_model=InvitationPreview)
async def lookup_invitation(payload: InvitationLookup, session: SessionDep) -> InvitationPreview:
    """Что за приглашение — до того, как соглашаться.

    Ссылка в теле, а не в адресе: адрес попадает в журналы прокси и
    сервера, а это одноразовый ключ ко входу.
    """
    service = InvitationService(session)
    invitation = await service.lookup(payload.token)
    inviter = invitation.invited_by

    return InvitationPreview(
        organization_name=invitation.organization.name,
        email=invitation.email,
        role=invitation.role,
        invited_by=None if inviter is None else (inviter.full_name or inviter.email),
        expires_at=invitation.expires_at,
        has_account=await service.has_account(invitation),
    )


@router.post("/auth/invitations/accept", response_model=AcceptedPublic)
async def accept_invitation(
    payload: InvitationAccept, user: OptionalUserDep, session: SessionDep
) -> AcceptedPublic:
    """Принять приглашение.

    Вошедший с той же почтой получает участие. Человек без учётной записи
    заводит её здесь же — паролем из формы — и она действующая сразу:
    одобрение площадки заменяет тот, кто его позвал. Токенов в ответе нет:
    новая запись входит обычным входом по своему паролю.
    """
    accepted = await InvitationService(session).accept(
        payload.token, user=user, password=payload.password, full_name=payload.full_name
    )

    return AcceptedPublic(
        organization_id=accepted.organization.id,
        organization_name=accepted.organization.name,
        email=accepted.user.email,
        new_account=accepted.new_account,
    )
