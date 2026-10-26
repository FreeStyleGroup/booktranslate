"""Файл из хранилища — во временную копию на диске.

Разборщики работают с файлом на диске, а не с потоком: и python-docx, и
zipfile читают с произвольного места, чего у потока нет. Копию просят
двое — проверка файла и предложение глав, — и способ её получить один:
две реализации однажды разошлись бы в том, убирается ли копия при ошибке.
"""

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.services.storage import ObjectStorage


@asynccontextmanager
async def local_copy(storage: ObjectStorage, storage_key: str) -> AsyncIterator[Path]:
    """Путь к временной копии объекта; копия удаляется в любом случае."""
    descriptor, name = tempfile.mkstemp(prefix="booktranslate-source-")
    path = Path(name)

    try:
        with os.fdopen(descriptor, "wb") as handle:
            async for chunk in storage.stream(storage_key):
                # Запись на диск — блокирующая работа. В потоке событий она
                # остановила бы обслуживание остальных запросов.
                await asyncio.to_thread(handle.write, chunk)

        yield path
    finally:
        path.unlink(missing_ok=True)
