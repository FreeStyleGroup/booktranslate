"""Перевод ошибок предметной области в коды ответа.

Одно место вместо `try/except` в каждом обработчике: правило «объект не
найден — это 404» не должно повторяться тридцать раз, чтобы однажды
разойтись в тридцать первом.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


# Ошибки разбора запроса. Их текст дословно доходит до человека, поэтому он на русском. Значения
# полей в ответ не возвращаются: незачем отдавать обратно то, что прислали.
_VALIDATION: dict[str, str] = {
    "missing": "Не заполнено обязательное поле",
    "extra_forbidden": "В запросе лишнее поле",
    "string_type": "Нужен текст",
    "enum": "Такого значения нет в списке",
    "literal_error": "Такого значения нет в списке",
    "uuid_parsing": "Неверный идентификатор",
    "uuid_type": "Неверный идентификатор",
    "int_parsing": "Нужно целое число",
    "int_type": "Нужно целое число",
    "bool_parsing": "Нужно значение «да» или «нет»",
    "bool_type": "Нужно значение «да» или «нет»",
    "list_type": "Нужен список",
    "dict_type": "Запрос повреждён",
    "model_attributes_type": "Запрос повреждён",
    "json_invalid": "Запрос повреждён",
    "value_error.email": "Неверный адрес почты",
}
_VALIDATION_DEFAULT = "Проверьте введённые данные"

# То, что отвечает сам веб-сервер, минуя наш код.
_HTTP: dict[int, str] = {
    status.HTTP_401_UNAUTHORIZED: "Нужно войти",
    status.HTTP_403_FORBIDDEN: "Нет доступа",
    status.HTTP_404_NOT_FOUND: "Не найдено",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Такой запрос здесь не поддерживается",
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "Запрос слишком большой",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Такой тип данных не поддерживается",
}
_HTTP_DEFAULT = "Запрос не выполнен"


def _validation_message(error: Mapping[str, Any]) -> str:
    kind = str(error.get("type", ""))
    context = error.get("ctx") or {}

    if kind == "string_too_short":
        return f"Слишком коротко: нужно не меньше {context.get('min_length')} знаков"
    if kind == "string_too_long":
        return f"Слишком длинно: не больше {context.get('max_length')} знаков"
    if kind == "too_short":
        return f"Слишком мало значений: нужно не меньше {context.get('min_length')}"
    if kind == "too_long":
        return f"Слишком много значений: не больше {context.get('max_length')}"
    if kind in ("greater_than_equal", "greater_than"):
        return f"Значение должно быть не меньше {context.get('ge', context.get('gt'))}"
    if kind in ("less_than_equal", "less_than"):
        return f"Значение должно быть не больше {context.get('le', context.get('lt'))}"
    if kind == "value_error":
        # Текст собственных проверок уже написан по-русски; в адресе почты текст чужой.
        message = str(context.get("error", ""))
        return message if _is_russian(message) else _VALIDATION_DEFAULT

    return _VALIDATION.get(kind, _VALIDATION_DEFAULT)


def _is_russian(text: str) -> bool:
    return any("а" <= letter.lower() <= "я" or letter in "ёЁ" for letter in text)


async def handle_validation_error(request: Request, exc: Exception) -> Response:
    """Запрос не прошёл схему: тот же ответ 422, но текст на русском."""
    if not isinstance(exc, RequestValidationError):
        raise exc

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": [
                {
                    "loc": [str(part) for part in error.get("loc", ())],
                    "msg": _validation_message(error),
                    "type": error.get("type"),
                }
                for error in exc.errors()
            ]
        },
    )


async def handle_http_error(request: Request, exc: Exception) -> Response:
    """Ответы самого веб-сервера: английский текст заменяется русским, смысл кода тот же."""
    if not isinstance(exc, StarletteHTTPException):
        raise exc

    detail = (
        exc.detail if _is_russian(str(exc.detail)) else _HTTP.get(exc.status_code, _HTTP_DEFAULT)
    )

    return JSONResponse(
        status_code=exc.status_code, content={"detail": detail}, headers=exc.headers
    )
