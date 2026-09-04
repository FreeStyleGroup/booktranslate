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
from app.models.organization import Membership, Organization, Role, User
from app.models.session import RefreshSession
from app.schemas.auth import TokenPair
from app.services.errors import AuthError, ConflictError
from app.services.slug import slugify


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
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        existing = await self._session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise ConflictError("Пользователь с такой почтой уже зарегистрирован")

        user = User(email=email, full_name=full_name, password_hash=hash_password(password))
        organization = Organization(
            name=organization_name,
            slug=await self._unique_slug(slugify(organization_name, fallback="org")),
        )
        # Тот, кто завёл организацию, становится её владельцем: иначе
        # первым же действием оказалось бы некому выдать права.
        membership = Membership(organization=organization, user=user, role=Role.OWNER)

        self._session.add_all([user, organization, membership])
        await self._session.flush()

        tokens = await self._issue_tokens(
            user=user,
            organization_id=organization.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self._session.commit()

        return tokens

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        user = await self._session.scalar(select(User).where(User.email == email))

        # Один и тот же ответ на «нет такого пользователя», «неверный
        # пароль» и «учётная запись отключена»: разные ответы позволяют
        # выяснить, кто здесь зарегистрирован.
        if user is None or user.password_hash is None or not user.is_active:
            raise AuthError("Неверная почта или пароль")

        if not verify_password(password, user.password_hash):
            raise AuthError("Неверная почта или пароль")

        # Единственный момент, когда пароль известен в открытом виде, —
        # здесь. Если параметры Argon2 ужесточились, пересчитываем сейчас.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

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
        if user is None or not user.is_active:
            raise AuthError("Учётная запись недоступна")

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
