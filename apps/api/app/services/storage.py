"""Хранилище исходных файлов.

Отдельный слой, а не работа с путями прямо в сервисе документов: сегодня
файлы лежат в каталоге рядом с приложением, завтра — в объектном хранилище,
и переезд не должен трогать ни модель, ни обработчики. Поэтому в базе
хранится ключ (строка), а не путь, а операций всего три: положить, отдать
потоком, удалить.
"""

import asyncio
import shutil
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

# Размер куска при чтении и записи. Мегабайт — компромисс: меньше даёт
# лишние системные вызовы на файле в сотни мегабайт, больше без пользы
# занимает память на каждом параллельном запросе.
CHUNK_BYTES = 1024 * 1024


class StorageKeyError(ValueError):
    """Ключ ведёт за пределы хранилища.

    Отдельный тип, потому что это не «файл не найден», а попытка выйти
    из каталога — такое нужно видеть в логах отдельно.
    """


class ObjectStorage(Protocol):
    """Что обязано уметь хранилище файлов."""

    async def put(self, key: str, source: Path) -> None:
        """Положить файл под ключом. Исходный файл после этого не нужен."""
        ...

    def stream(self, key: str) -> AsyncIterator[bytes]:
        """Отдать содержимое кусками."""
        ...

    async def delete(self, key: str) -> None:
        """Удалить объект. Отсутствие объекта — не ошибка."""
        ...


class LocalStorage:
    """Файлы в каталоге на диске.

    Годится для разработки и для одного сервера. Как только приложение
    поедет в несколько экземпляров, на это место встанет S3-совместимая
    реализация — интерфейс останется тем же.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        """Путь по ключу с проверкой, что он не ведёт наружу.

        Ключ формируется приложением, но проверка всё равно нужна: одна
        будущая правка, пропускающая в ключ имя файла от пользователя, —
        и «../../etc» перезапишет чужое.
        """
        if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
            raise StorageKeyError(f"Недопустимый ключ хранилища: {key!r}")

        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageKeyError(f"Ключ ведёт за пределы хранилища: {key!r}")

        return candidate

    async def put(self, key: str, source: Path) -> None:
        target = self._path(key)

        def write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            # move, а не copy: временный файл всё равно наш и больше не
            # нужен, а копия на файле в сотни мегабайт стоит вдвое дороже.
            shutil.move(str(source), str(target))

        await asyncio.to_thread(write)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        handle = await asyncio.to_thread(path.open, "rb")

        try:
            while chunk := await asyncio.to_thread(handle.read, CHUNK_BYTES):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        # missing_ok: удаление того, чего нет, — достигнутая цель, а не
        # ошибка. Иначе повторная попытка удалить документ падала бы.
        await asyncio.to_thread(path.unlink, True)


@lru_cache
def get_storage() -> ObjectStorage:
    """Хранилище приложения.

    Функция, а не глобальный объект: так её подменяют в тестах через
    зависимости FastAPI, не трогая настройки процесса.
    """
    return LocalStorage(Path(get_settings().storage_root))
