"""Управление доступом на площадке.

Регистрация — это заявка, а не пропуск: пока администратор не открыл
доступ, войти нельзя. Здесь всё, что администратор с этими заявками делает:
смотрит список, открывает и закрывает доступ, заводит учётную запись сам.

**Это не роли организации.** Роль говорит, что человек может у себя в
рабочем пространстве; здесь решается, пускать ли его на площадку вообще.
Смешивать нельзя: владелец своей организации не должен решать, кого
пускать в чужие.

**Закрытый доступ гасит сессии.** Иначе «доступ приостановлен» означает
«приостановлен, когда закончится текущий токен», и человек, которого
только что отключили, спокойно доработает смену.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_password, hash_password
from app.models.organization import Membership, Organization, Role, User, UserStatus
from app.models.session import RefreshSession
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.slug import slugify


@dataclass(slots=True)
class UserCard:
    """Пользователь в списке администратора.

    Организации приложены сразу: без них список — это столбец почт, по
    которому нельзя понять, кто пришёл и зачем.
    """

    user: User
    organizations: list[str] = field(default_factory=list)
    # Почта того, кто последним менял состояние доступа. Не идентификатор:
    # в списке нужен человек, а не строка из 36 знаков.
    changed_by: str | None = None


@dataclass(slots=True)
class CreatedUser:
    """Заведённая администратором учётная запись и её пароль.

    Пароль возвращается ровно один раз — в базе только хеш. Показать его
    второй раз будет неоткуда, и это не недоработка: пароль, который можно
    подсмотреть в интерфейсе, не пароль.
    """

    user: User
    password: str
    organization: Organization


class AdminService:
    """Действия администратора площадки.

    Права проверяются на входе в обработчик (`app/api/deps.py`), а не здесь:
    сервис должен оставаться вызываемым из консольной команды, где никакого
    «текущего пользователя» нет вовсе. Кто именно распорядился, приходит
    параметром — и попадает в запись о смене состояния.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(
        self,
        *,
        status: UserStatus | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserCard]:
        """Список пользователей: кто, когда зарегистрировался и в каком состоянии.

        Ожидающие идут первыми независимо от отбора: список открывают ради
        них, а не ради тех, у кого всё в порядке.
        """
        statement: Select[tuple[User]] = select(User)

        if status is not None:
            statement = statement.where(User.status == status)

        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(User.email.ilike(pattern), User.full_name.ilike(pattern))
            )

        statement = statement.order_by(
            # Ожидающие первыми — порядок значений перечисления в Postgres
            # совпадает с порядком объявления: PENDING, ACTIVE, SUSPENDED.
            User.status,
            User.created_at.desc(),
        )

        users = list(await self._session.scalars(statement.limit(limit).offset(offset)))

        return await self._cards(users)

    async def counts(self) -> dict[UserStatus, int]:
        """Сколько учётных записей в каждом состоянии.

        Отдельным запросом, а не подсчётом на странице списка: число
        ожидающих нужно показывать всегда, а страница показывает двадцать
        строк из двух тысяч.
        """
        rows = await self._session.execute(select(User.status, func.count()).group_by(User.status))

        found = {status: 0 for status in UserStatus}
        for status, amount in rows.all():
            found[status] = amount

        return found

    async def set_status(self, user_id: uuid.UUID, status: UserStatus, *, by: User) -> UserCard:
        """Открыть или закрыть доступ."""
        if status is UserStatus.PENDING:
            raise InvalidInputError("Вернуть заявку в состояние «ждёт решения» нельзя")

        user = await self._session.get(User, user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")

        # Самому себе доступ не закрывают. Это не забота о комфорте: закрыв
        # доступ единственному администратору, площадку не откроет уже
        # никто, кроме как командой на сервере.
        if user.id == by.id and status is UserStatus.SUSPENDED:
            raise ConflictError("Нельзя закрыть доступ самому себе")

        user.status = status
        user.status_changed_at = datetime.now(UTC)
        user.status_changed_by_id = by.id

        if status is UserStatus.SUSPENDED:
            await self._revoke_sessions(user.id)

        await self._session.commit()
        await self._session.refresh(user)

        cards = await self._cards([user])

        return cards[0]

    async def create_user(
        self,
        *,
        email: str,
        full_name: str | None,
        organization_name: str | None,
        organization_id: uuid.UUID | None,
        role: Role,
        by: User,
    ) -> CreatedUser:
        """Завести учётную запись с выданным паролем.

        Заведённая администратором запись сразу действующая: одобрять
        собственное решение второй раз незачем.

        Организация либо новая по названию, либо существующая по
        идентификатору — второе нужно, чтобы добавить коллегу в уже
        работающее пространство, а не плодить одноимённые.
        """
        normalized = email.strip().lower()

        existing = await self._session.scalar(select(User).where(User.email == normalized))
        if existing is not None:
            raise ConflictError("Пользователь с такой почтой уже заведён")

        organization = await self._organization(organization_id, organization_name)
        password = generate_password()

        user = User(
            email=normalized,
            full_name=full_name,
            password_hash=hash_password(password),
            status=UserStatus.ACTIVE,
            status_changed_at=datetime.now(UTC),
            status_changed_by_id=by.id,
        )
        membership = Membership(organization=organization, user=user, role=role)

        self._session.add_all([user, membership])
        await self._session.commit()
        await self._session.refresh(user)

        return CreatedUser(user=user, password=password, organization=organization)

    async def _organization(
        self, organization_id: uuid.UUID | None, organization_name: str | None
    ) -> Organization:
        if organization_id is not None:
            organization = await self._session.get(Organization, organization_id)

            if organization is None:
                raise NotFoundError("Рабочее пространство не найдено")

            return organization

        name = (organization_name or "").strip()
        if not name:
            raise InvalidInputError("Нужно название рабочего пространства или его идентификатор")

        organization = Organization(
            name=name, slug=await self._unique_slug(slugify(name, fallback="org"))
        )
        self._session.add(organization)

        return organization

    async def _cards(self, users: Sequence[User]) -> list[UserCard]:
        """Дополнить пользователей тем, что нужно в списке.

        Два запроса на всю страницу, а не по два на строку: сотня
        пользователей — это сотня походов в базу там, где хватает двух.
        """
        if not users:
            return []

        ids = [user.id for user in users]

        rows = await self._session.execute(
            select(Membership.user_id, Organization.name)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.user_id.in_(ids))
            .order_by(Organization.name)
        )

        organizations: dict[uuid.UUID, list[str]] = {}
        for user_id, name in rows.all():
            organizations.setdefault(user_id, []).append(name)

        changed_ids = {user.status_changed_by_id for user in users if user.status_changed_by_id}
        editors: dict[uuid.UUID, str] = {}

        if changed_ids:
            editor_rows = await self._session.execute(
                select(User.id, User.email).where(User.id.in_(list(changed_ids)))
            )
            editors = {row[0]: row[1] for row in editor_rows.all()}

        return [
            UserCard(
                user=user,
                organizations=organizations.get(user.id, []),
                changed_by=editors.get(user.status_changed_by_id)
                if user.status_changed_by_id
                else None,
            )
            for user in users
        ]

    async def _revoke_sessions(self, user_id: uuid.UUID) -> None:
        rows = await self._session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        )
        moment = datetime.now(UTC)

        for row in rows:
            row.revoked_at = moment

    async def _unique_slug(self, base: str) -> str:
        candidate = base
        suffix = 2

        while await self._session.scalar(
            select(Organization.id).where(Organization.slug == candidate)
        ):
            candidate = f"{base}-{suffix}"
            suffix += 1

        return candidate
