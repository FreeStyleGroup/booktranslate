"""Приём загружаемых файлов.

Общее место для всех ручек, которые что-то принимают: документ, словарь,
термбазу. Потолок размера обязан проверяться по мере чтения, а не после —
узнать о превышении, когда гигабайт уже в памяти процесса, поздно и дорого,
а `await file.read()` без счётчика делает ровно это.
"""

from collections.abc import AsyncIterator

from fastapi import UploadFile

from app.services.errors import PayloadTooLargeError
from app.services.storage import CHUNK_BYTES


async def chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    """Содержимое загрузки кусками.

    Файл читается порциями, а не целиком: руководство на восемьсот страниц
    в памяти процесса — это отказ сервера при нескольких одновременных
    загрузках.
    """
    while chunk := await upload.read(CHUNK_BYTES):
        yield chunk


async def read_capped(upload: UploadFile, *, limit_bytes: int) -> bytes:
    """Прочитать загрузку целиком, но не больше разрешённого.

    Словарь разбирается из памяти — построчно его не разобрать ни в CSV с
    кавычками, ни в XML, — но «из памяти» не значит «сколько принесут».
    """
    parts: list[bytes] = []
    size = 0

    async for chunk in chunks(upload):
        size += len(chunk)

        if size > limit_bytes:
            raise PayloadTooLargeError(f"Файл больше разрешённых {limit_bytes // (1024 * 1024)} МБ")

        parts.append(chunk)

    return b"".join(parts)
