"""Подстановка переведённых картинок в готовый файл по месту.

DOCX и EPUB — это архивы, картинки лежат в них отдельными частями. Часть находится по сумме
оригинала, поэтому путь внутри архива и разбор разметки не нужны. Перевод сохранён в том же
формате, что оригинал, и описание файла остаётся верным."""

import hashlib
import io
import zipfile

from app.services.export.base import ExportError

# Сколько распакованного готовы прочитать из одной части: архив собран из чужого исходника.
_PART_MAX = 256 * 1024 * 1024

ZIP_SUFFIXES = (".docx", ".epub")


def replace_images(content: bytes, replacements: dict[str, bytes]) -> bytes:
    """Новый архив, в котором картинки заменены. `replacements`: сумма оригинала → новые байты."""
    if not replacements:
        return content

    try:
        source = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise ExportError("Готовый файл не читается как архив") from error

    buffer = io.BytesIO()

    with source, zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            if info.file_size > _PART_MAX:
                raise ExportError(f"Часть файла {info.filename} слишком велика")

            data = source.read(info)
            digest = hashlib.sha256(data).hexdigest()
            # Описание части берётся прежним: порядок и способ сжатия важны для EPUB.
            target.writestr(info, replacements.get(digest, data))

    return buffer.getvalue()
