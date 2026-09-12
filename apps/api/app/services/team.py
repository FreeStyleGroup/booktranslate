"""Команда рабочего пространства: кто в нём работает и кого позвать.

Доступ в пространство открывает его владелец, а не администратор площадки.
Площадка одобряет заказчика — организацию; кого заказчик пускает к своим
книгам, решает он сам, и второе одобрение тут было бы недоверием к тому,
кому уже доверили пространство. Поэтому приглашённый по ссылке получает
действующую учётную запись сразу.

Три правила про роли, и все три — от одного страха: остаться без хозяина.

- **Владельца назначает и снимает только владелец.** Администратор
  распоряжается людьми, но не самим пространством.
- **Свою роль не меняют и себя не удаляют.** Единственный владелец,
  понизивший себя, оставил бы пространство без того, кто может это
  исправить.
- **Приглашение — на почту, ссылка одноразовая и с сроком.** Ссылка, живущая
  вечно, — это пароль, который никто не менял.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import generate_refresh_token, hash_password, hash_refresh_token
from app.models.organization import Membership, Organization, Role, User, UserStatus
from app.models.team import Invitation
from app.services.base import TenantService
from app.services.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
)
from app.services.notify import Delivery, EmailChannel, Message

# Кто распоряжается составом команды. Владелец проходит по определению.
MANAGING_ROLES = (Role.ADMIN,)

# Срок ссылки. Неделя: письмо лежит в ящике до понедельника, а ссылка,
# живущая месяцами, — это пароль, который никто не менял.
INVITATION_DAYS = 7

# Порядок ролей в списке — от хозяина к наблюдателю: так список отвечает
# на «кто здесь главный» с первой строки.
ROLE_ORDER = (Role.OWNER, Role.ADMIN, Role.MANAGER, Role.TRANSLATOR, Role.REVIEWER, Role.VIEWER)

# Роль словами — для письма. Витрина держит свои подписи, но письмо
# уходит отсюда, и «translator» в нём читалось бы как техническая утечка.
ROLE_LABELS = {
    Role.OWNER: "владелец",
    Role.ADMIN: "администратор",
    Role.MANAGER: "менеджер",
    Role.TRANSLATOR: "переводчик",
    Role.REVIEWER: "редактор",
    Role.VIEWER: "наблюдатель",
}


@dataclass(slots=True)
class Invited:
    """Выписанное приглашение вместе со ссылкой и судьбой письма.

    Ссылка показывается пригласившему один раз: если почта площадки не
    настроена или письмо не дошло, он передаст её сам. В базе — только хеш.
    """

    invitation: Invitation
    link: str
    delivery: Delivery


@dataclass(slots=True)
class Accepted:
    user: User
    organization: Organization
    # Учётная запись заведена только что. Витрине это нужно, чтобы решить,
    # входить ли по паролю из формы или человек уже внутри.
    new_account: bool


def invitation_message(
    *, organization: str, role: Role, invited_by: str | None, link: str
) -> Message:
    who = f"{invited_by} приглашает вас" if invited_by else "Вас приглашают"

    return Message(
        subject=f"Приглашение в рабочее пространство «{organization}»",
        body=(
            f"{who} в рабочее пространство «{organization}» на BookTranslate — "
            f"роль: {ROLE_LABELS[role]}.\n\n"
            f"Принять приглашение: {link}\n\n"
            f"Ссылка действует {INVITATION_DAYS} дней и одноразовая. "
            "Если вы не ждали этого письма, просто не открывайте ссылку."
        ),
    )


class TeamService(TenantService):
    async def members(self) -> list[Membership]:
        """Участники с их учётными записями, от владельца к наблюдателю."""
        rows = list(
            await self._session.scalars(self._memberships().options(selectinload(Membership.user)))
        )

        rows.sort(key=lambda row: (ROLE_ORDER.index(row.role), row.user.email))

        return rows

    async def invitations(self) -> list[Invitation]:
        """Открытые приглашения — не принятые. Просроченные тоже: их надо
        видеть, чтобы отозвать или выписать заново."""
        return list(
            await self._session.scalars(
                self.scoped(Invitation)
                .options(selectinload(Invitation.invited_by))
                .where(Invitation.accepted_at.is_(None))
                .order_by(Invitation.created_at.desc())
            )
        )

    async def invite(self, *, email: str, role: Role, web_url: str) -> Invited:
        """Выписать приглашение и отправить письмо.

        Повторное приглашение той же почты заменяет прежнее: у человека
        должна работать последняя ссылка, а не та, что он потерял.
        """
        self._context.require(*MANAGING_ROLES)
        self._check_grant(role)

        normalized = email.strip().lower()

        member = await self._session.scalar(
            self._memberships().join(User).where(User.email == normalized)
        )
        if member is not None:
            raise ConflictError("Этот человек уже в команде")

        previous = await self._session.scalar(
            self.scoped(Invitation).where(
                Invitation.email == normalized, Invitation.accepted_at.is_(None)
            )
        )
        if previous is not None:
            await self._session.delete(previous)
            await self._session.flush()

        token = generate_refresh_token()
        invitation = Invitation(
            organization_id=self.organization_id,
            email=normalized,
            role=role,
            token_hash=hash_refresh_token(token),
            invited_by_id=self._context.user.id,
            expires_at=datetime.now(UTC) + timedelta(days=INVITATION_DAYS),
        )
        self._session.add(invitation)
        await self._session.commit()
        await self._session.refresh(invitation, attribute_names=["organization", "invited_by"])

        link = f"{web_url.rstrip('/')}/join?token={token}"
        message = invitation_message(
            organization=invitation.organization.name,
            role=role,
            invited_by=self._context.user.full_name or self._context.user.email,
            link=link,
        )

        return Invited(
            invitation=invitation,
            link=link,
            delivery=await EmailChannel().send(normalized, message),
        )

    async def revoke(self, invitation_id: uuid.UUID) -> None:
        self._context.require(*MANAGING_ROLES)

        invitation = await self._session.scalar(
            self.scoped(Invitation).where(
                Invitation.id == invitation_id, Invitation.accepted_at.is_(None)
            )
        )
        if invitation is None:
            raise NotFoundError("Приглашение не найдено")

        await self._session.delete(invitation)
        await self._session.commit()

    async def change_role(self, user_id: uuid.UUID, role: Role) -> Membership:
        self._context.require(*MANAGING_ROLES)
        self._check_grant(role)

        membership = await self._membership(user_id)

        membership.role = role

        await self._session.commit()
        await self._session.refresh(membership, attribute_names=["user"])

        return membership

    async def remove(self, user_id: uuid.UUID) -> None:
        """Убрать из команды. Учётная запись остаётся: у человека могут быть
        другие пространства, а закрыть доступ на площадку может только её
        администратор."""
        self._context.require(*MANAGING_ROLES)

        membership = await self._membership(user_id)

        await self._session.delete(membership)
        await self._session.commit()

    async def _membership(self, user_id: uuid.UUID) -> Membership:
        """Участие, которое разрешено трогать этому человеку."""
        if user_id == self._context.user.id:
            raise ConflictError(
                "Свою роль не меняют и себя не удаляют: попросите другого владельца"
            )

        membership = await self._session.scalar(
            self._memberships()
            .options(selectinload(Membership.user))
            .where(Membership.user_id == user_id)
        )
        if membership is None:
            raise NotFoundError("Участник не найден")

        if membership.role is Role.OWNER and self._context.role is not Role.OWNER:
            raise AccessDeniedError("Роль владельца меняет только владелец")

        return membership

    def _memberships(self) -> Select[tuple[Membership]]:
        """Участия этого пространства.

        Не `scoped`: участие — связь человека с организацией, а не её
        данные, и под общий признак принадлежности оно не подведено. Условие
        то же, и стоит оно здесь одно на все запросы.
        """
        return select(Membership).where(Membership.organization_id == self.organization_id)

    def _check_grant(self, role: Role) -> None:
        if role is Role.OWNER and self._context.role is not Role.OWNER:
            raise AccessDeniedError("Назначить владельца может только владелец")


class InvitationService:
    """Принятие приглашения — снаружи пространства.

    Без контекста: у того, кто идёт по ссылке, ещё нет ни организации, ни,
    возможно, учётной записи.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lookup(self, token: str) -> Invitation:
        """Приглашение по ссылке — живое: не принятое и не просроченное."""
        invitation = await self._session.scalar(
            select(Invitation)
            .options(selectinload(Invitation.organization), selectinload(Invitation.invited_by))
            .where(Invitation.token_hash == hash_refresh_token(token))
        )

        if invitation is None or invitation.accepted_at is not None:
            raise NotFoundError("Приглашение не найдено: ссылка отозвана или уже использована")

        if invitation.expires_at <= datetime.now(UTC):
            raise ConflictError("Срок приглашения истёк — попросите прислать новое")

        return invitation

    async def has_account(self, invitation: Invitation) -> bool:
        return (
            await self._session.scalar(select(User.id).where(User.email == invitation.email))
            is not None
        )

    async def accept(
        self,
        token: str,
        *,
        user: User | None,
        password: str | None,
        full_name: str | None,
    ) -> Accepted:
        """Принять приглашение.

        Два пути. Вошедший человек с той же почтой просто получает участие.
        Человек без учётной записи заводит её здесь же — паролем из формы —
        и она действующая сразу: одобрение площадки заменяет тот, кто его
        позвал. Учётная запись с этой почтой, в которую не вошли, — не
        принимается: иначе ссылка из письма открывала бы чужую учётную
        запись любому, кто её перехватил.
        """
        invitation = await self.lookup(token)
        existing = await self._session.scalar(select(User).where(User.email == invitation.email))
        now = datetime.now(UTC)

        if user is not None:
            if user.email != invitation.email:
                raise AccessDeniedError(f"Приглашение выписано на другую почту: {invitation.email}")
            target = user
            new_account = False
        elif existing is not None:
            raise AccessDeniedError("Войдите под этой почтой, и приглашение примется")
        else:
            if not password:
                raise InvalidInputError("Для новой учётной записи нужен пароль")

            target = User(
                email=invitation.email,
                full_name=(full_name or "").strip() or None,
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
                status_changed_at=now,
                status_changed_by_id=invitation.invited_by_id,
            )
            self._session.add(target)
            await self._session.flush()
            new_account = True

        membership = await self._session.scalar(
            select(Membership).where(
                Membership.organization_id == invitation.organization_id,
                Membership.user_id == target.id,
            )
        )
        if membership is None:
            self._session.add(
                Membership(
                    organization_id=invitation.organization_id,
                    user_id=target.id,
                    role=invitation.role,
                )
            )

        invitation.accepted_at = now
        invitation.accepted_by_id = target.id

        await self._session.commit()

        return Accepted(user=target, organization=invitation.organization, new_account=new_account)
