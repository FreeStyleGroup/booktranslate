"""Регистрация, вход и обновление доступа.

Сервис владеет транзакцией: обработчик получает готовый результат и не
знает ни про сессии SQLAlchemy, ни про то, в каком порядке пишутся записи.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    verify_password,
)
from app.models.organization import Membership, Organization, Role, User, UserStatus
from app.models.session import RefreshSession
from app.schemas.auth import TokenPair
from app.services.errors import AccessDeniedError, AuthError
from app.services.slug import slugify

# Что отвечают человеку, чей доступ ещё не открыт или уже закрыт. Сообщения
# разные: «вас ещё не рассмотрели» и «вам закрыли доступ» требуют разных
# действий, и общая формулировка заставила бы писать в поддержку обоих.
PENDING_MESSAGE = "Заявка на доступ отправлена администратору и ещё не одобрена"
SUSPENDED_MESSAGE = "Доступ к учётной записи приостановлен администратором"


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None,
        organization_name: str,
    ) -> User | None:
        """Заявка на доступ.

        Регистрация не пускает внутрь и не выдаёт токенов: доступ открывает
        администратор. Рабочее пространство при этом создаётся сразу —
        человек назвал его при подаче заявки, и заводить его потом заново,
        уточняя название, значит потерять то, что уже сказано.

        Занятая почта — не ошибка наружу, а `None`. Ответ «такой уже есть»
        превращает форму регистрации в проверку, работает ли здесь человек
        с известным адресом. Вход это скрывает — одинаковый ответ на
        неверную почту и на неверный пароль, — и отдавать то же самое даром
        через соседнюю форму бессмысленно.
        """
        # Хеш считается до проверки, а не после: иначе занятая почта
        # отвечает заметно быстрее свободной, и разница во времени говорит
        # ровно то, что мы только что перестали говорить словами.
        password_hash = hash_password(password)

        existing = await self._session.scalar(select(User).where(User.email == email))
        if existing is not None:
            return None

        user = User(
            email=email,
            full_name=full_name,
            password_hash=password_hash,
            status=UserStatus.PENDING,
        )
        organization = Organization(
            name=organization_name,
            slug=await self._unique_slug(slugify(organization_name, fallback="org")),
        )
        # Тот, кто завёл организацию, становится её владельцем: иначе
        # первым же действием оказалось бы некому выдать права.
        membership = Membership(organization=organization, user=user, role=Role.OWNER)

        self._session.add_all([user, organization, membership])
        await self._session.commit()
        await self._session.refresh(user)

        return user

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        user = await self._session.scalar(select(User).where(User.email == email))

        # Один и тот же ответ на «нет такого пользователя» и «неверный
        # пароль»: разные ответы позволяют выяснить перебором, кто здесь
        # зарегистрирован.
        if user is None or user.password_hash is None:
            raise AuthError("Неверная почта или пароль")

        if not verify_password(password, user.password_hash):
            raise AuthError("Неверная почта или пароль")

        # Состояние доступа сообщается только после верного пароля. До него
        # это подсказка перебирающему, после — ответ человеку, который свою
        # учётную запись и так знает: иначе он будет считать, что ошибся
        # паролем, и писать в поддержку об этом.
        self._require_active(user)

        # Единственный момент, когда пароль известен в открытом виде, —
        # здесь. Если параметры Argon2 ужесточились, пересчитываем сейчас.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        user.last_login_at = datetime.now(UTC)

        organization_id = await self._session.scalar(
            select(Membership.organization_id).where(Membership.user_id == user.id).limit(1)
        )

        tokens = await self._issue_tokens(
            user=user,
            organization_id=organization_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self._session.commit()

        return tokens

    async def refresh(
        self,
        *,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        token_hash = hash_refresh_token(refresh_token)
        session_row = await self._session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )

        if session_row is None:
            raise AuthError("Токен обновления не найден")

        now = datetime.now(UTC)

        if session_row.revoked_at is not None:
            # По отозванному токену пришли повторно. Либо это гонка
            # клиента, либо украденная копия — различить нельзя, поэтому
            # гасим все сессии пользователя и заставляем войти заново.
            await self._revoke_all(session_row.user_id, now)
            await self._session.commit()
            raise AuthError("Токен обновления уже использован; сессии сброшены")

        if session_row.expires_at <= now:
            raise AuthError("Срок действия токена обновления истёк")

        user = await self._session.get(User, session_row.user_id)
        if user is None:
            raise AuthError("Учётная запись недоступна")

        # Доступ мог быть закрыт уже после входа: обновление — единственное
        # место, где длинная сессия сверяется с текущим состоянием.
        self._require_active(user)

        organization_id = await self._session.scalar(
            select(Membership.organization_id).where(Membership.user_id == user.id).limit(1)
        )

        tokens, new_session = await self._create_session(
            user=user,
            organization_id=organization_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        # Старый токен гасится и помечается, чем заменён: цепочка нужна,
        # чтобы при повторном использовании было видно, откуда она растёт.
        session_row.revoked_at = now
        session_row.replaced_by_id = new_session.id

        await self._session.commit()

        return tokens

    async def logout(self, *, refresh_token: str) -> None:
        token_hash = hash_refresh_token(refresh_token)
        session_row = await self._session.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )

        # Выход идемпотентен: неизвестный или уже погашенный токен —
        # не ошибка, цель «дальше по нему не входят» достигнута.
        if session_row is not None and session_row.revoked_at is None:
            session_row.revoked_at = datetime.now(UTC)
            await self._session.commit()

    @staticmethod
    def _require_active(user: User) -> None:
        if user.status is UserStatus.PENDING:
            raise AccessDeniedError(PENDING_MESSAGE)

        if user.status is UserStatus.SUSPENDED:
            raise AccessDeniedError(SUSPENDED_MESSAGE)

    async def _issue_tokens(
        self,
        *,
        user: User,
        organization_id: uuid.UUID | None,
        user_agent: str | None,
        ip_address: str | None,
    ) -> TokenPair:
        tokens, _ = await self._create_session(
            user=user,
            organization_id=organization_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return tokens

    async def _create_session(
        self,
        *,
        user: User,
        organization_id: uuid.UUID | None,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[TokenPair, RefreshSession]:
        settings = get_settings()

        refresh_token = generate_refresh_token()
        session_row = RefreshSession(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=user_agent[:400] if user_agent else None,
            ip_address=ip_address,
        )
        self._session.add(session_row)
        await self._session.flush()

        pair = TokenPair(
            access_token=create_access_token(user.id, organization_id),
            refresh_token=refresh_token,
            expires_in=settings.access_token_ttl_minutes * 60,
        )

        return pair, session_row

    async def _revoke_all(self, user_id: uuid.UUID, moment: datetime) -> None:
        rows = await self._session.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        )
        for row in rows:
            row.revoked_at = moment

    async def _unique_slug(self, base: str) -> str:
        """Свободное короткое имя.

        Уникальность стережёт ограничение в базе; здесь — попытка выбрать
        читаемое имя, а не полагаться на случайный суффикс сразу.
        """
        candidate = base
        suffix = 2
        while await self._session.scalar(
            select(Organization.id).where(Organization.slug == candidate)
        ):
            candidate = f"{base}-{suffix}"
            suffix += 1

        return candidate
