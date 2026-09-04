"""Пароли и токены.

Слой намеренно тонкий и без обращений к базе: он занимается только
криптографией, а решения «кто вошёл» и «что ему можно» принимает сервис.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher: Final = PasswordHasher()

TOKEN_TYPE_ACCESS: Final = "access"
TOKEN_TYPE_REFRESH: Final = "refresh"


class TokenError(Exception):
    """Токен не разобран: истёк, подделан или не того типа."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля.

    Возвращает False на любом несовпадении, включая испорченный хеш:
    вызывающему коду важен один ответ «пустить или нет», а разница между
    «пароль не тот» и «в базе мусор» наружу не выносится намеренно —
    по ней подбирают существующие учётные записи.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Пора ли пересчитать хеш под текущие параметры Argon2.

    Параметры со временем ужесточаются; хеши, посчитанные старыми, надо
    обновлять при очередном успешном входе — другого момента, когда пароль
    известен в открытом виде, не будет.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def create_access_token(user_id: uuid.UUID, organization_id: uuid.UUID | None = None) -> str:
    """Токен доступа.

    Организация кладётся в токен, чтобы каждый запрос не ходил за ней в
    базу. Права по ней всё равно проверяются заново: токен говорит, от
    чьего имени пришёл запрос, а не что этому имени сейчас разрешено.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    if organization_id is not None:
        payload["org"] = str(organization_id)

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    # Тип проверяется явно: refresh-токен подписан тем же ключом, и без
    # этой проверки его приняли бы как пропуск с длинным сроком жизни.
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise TokenError("ожидался токен доступа")

    return payload


def generate_refresh_token() -> str:
    """Случайная строка обновления.

    Не JWT: refresh должен отзываться, а отозвать самодостаточный токен
    без обращения к хранилищу нельзя. Здесь — непредсказуемое значение,
    смысл которому придаёт запись в базе.
    """
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Хеш для хранения.

    В базе лежит SHA-256, а не сам токен: утёкшая копия таблицы сессий не
    должна давать вход. Argon2 здесь не нужен — значение уже случайное и
    длинное, перебирать в нём нечего, а сравнивать приходится на каждом
    обновлении.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
