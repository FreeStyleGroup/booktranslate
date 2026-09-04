"""Перевод ошибок предметной области в коды ответа.

Одно место вместо `try/except` в каждом обработчике: правило «объект не
найден — это 404» не должно повторяться тридцать раз, чтобы однажды
разойтись в тридцать первом.
"""

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from app.services.errors import (
    AccessDeniedError,
    AuthError,
    ConflictError,
    DomainError,
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedFormatError,
)

_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    AuthError: status.HTTP_401_UNAUTHORIZED,
    AccessDeniedError: status.HTTP_403_FORBIDDEN,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidInputError: status.HTTP_400_BAD_REQUEST,
    PayloadTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnsupportedFormatError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}


def _status_for(error: DomainError) -> int:
    """Код ответа по типу ошибки, с учётом наследования.

    Обход предков нужен, чтобы будущая ошибка, уточняющая существующую
    (например «почта уже занята» от `ConflictError`), получала осмысленный
    код сама, без правки этой таблицы.
    """
    for klass in type(error).__mro__:
        code = _STATUS_BY_ERROR.get(klass)
        if code is not None:
            return code

    return status.HTTP_500_INTERNAL_SERVER_ERROR


async def handle_domain_error(request: Request, exc: Exception) -> Response:
    """Обработчик доменных ошибок.

    Тип аргумента — `Exception`, потому что таким его объявляет Starlette;
    сузить подписью нельзя, поэтому сужаем проверкой. Чужое исключение
    пробрасывается дальше, а не превращается в невнятный ответ.
    """
    if not isinstance(exc, DomainError):
        raise exc

    code = _status_for(exc)
    headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None

    return JSONResponse(status_code=code, content={"detail": str(exc)}, headers=headers)
