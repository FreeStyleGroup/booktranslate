"""Объекты главы при извлечении мастера: какие, из чего и с какой суммой.

Чистые функции над разобранным файлом — без базы, как и сопоставление
блоков. Сервис мастера решает, что из этого записать; здесь — только
содержимое объекта и его контрольная сумма.

Сумма считается по содержимому, а не по месту и не по подписи: рисунок,
у которого поправили подпись, — тот же рисунок с тем же кодом, а рисунок
в лучшем разрешении — новый, с родством к прежнему.
"""

import hashlib
import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.book_object import ObjectType
from app.services.parsers import ImageSource, ParsedBlock, ParsedSource, PlacedObject
from app.services.parsers.archives import ArchiveTooLargeError, check_archive, read_member
from app.services.parsers.labels import caption_label

# Изображения, которые экран показывает как есть. Остальное — TIFF, EMF,
# WMF из Word — хранится оригиналом, но в браузере не рисуется.
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# SVG узнаётся по корневому тегу в начале файла — после объявления XML,
# комментариев и пробелов. Дальше килобайта искать незачем.
_SVG_PROBE = 1024


@dataclass(frozen=True, slots=True)
class Picture:
    """Изображение рисунка, прочитанное из исходника."""

    data: bytes
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class Described:
    """Объект, готовый к записи: всё, кроме кода и места в версии."""

    type: ObjectType
    location: dict[str, Any]
    payload: dict[str, Any]
    checksum: str
    label: str | None


def in_chapter(source: ParsedSource, start: int, end: int) -> list[PlacedObject]:
    """Объекты, принадлежащие главе с блоками `[start, end)`.

    Объект с блоками — ячейками, листингом, подписью — принадлежит главе
    своего первого блока. Рисунок и формула блоков не имеют, и их глава —
    глава соседнего блока: следующего, если объект стоит в начале файла
    EPUB или страницы PDF, откуда этот блок, иначе предыдущего. Так
    картинка-заставка перед заголовком главы достаётся этой главе, а не
    концу предыдущей.
    """
    return [
        placed
        for placed in source.objects
        if source.blocks and start <= _home(source.blocks, placed) < end
    ]


def _home(blocks: Sequence[ParsedBlock], placed: PlacedObject) -> int:
    owned = [*placed.content, *([placed.caption] if placed.caption is not None else [])]
    if owned:
        return min(owned)

    after = placed.at if placed.at < len(blocks) else None
    before = placed.at - 1 if placed.at > 0 else None

    if after is None:
        return len(blocks) - 1

    if before is None:
        return after

    place = _file(placed.object.location)
    if place is not None and _file(blocks[after].location) == place != _file(
        blocks[before].location
    ):
        return after

    return before


def _file(location: dict[str, Any]) -> Any:
    return location.get("href", location.get("page"))


def read_pictures(path: Path, sources: Sequence[ImageSource]) -> dict[ImageSource, Picture]:
    """Байты изображений из исходного файла — одним открытием архива.

    Изображения, которого в архиве нет, в ответе нет: рисунок записывается
    без него и честно показывает, что оригинал не найден.
    """
    found: dict[ImageSource, Picture] = {}
    members = [source for source in sources if source.member is not None and source.data is None]

    for source in sources:
        if source.data is not None:
            found[source] = _picture(source.data)

    if not members:
        return found

    try:
        with zipfile.ZipFile(path) as archive:
            check_archive(archive)
            names = set(archive.namelist())

            for source in members:
                if source.member in names:
                    found[source] = _picture(read_member(archive, source.member or ""))
    except (zipfile.BadZipFile, ArchiveTooLargeError):
        # Файл уже разобран, значит архив читался. Не прочиталось
        # изображение — рисунок останется без оригинала, глава — с текстом.
        return found

    return found


def _picture(data: bytes) -> Picture:
    return Picture(data=data, sha256=hashlib.sha256(data).hexdigest(), media_type=media_type(data))


def media_type(data: bytes) -> str:
    """Тип изображения по его байтам, а не по имени файла.

    Имя в книге может быть каким угодно, а отдаётся изображение браузеру
    с тем типом, который здесь определён. Неопознанное — двоичный файл:
    браузер его не нарисует, но и не выполнит.
    """
    for signature, kind in _SIGNATURES:
        if data.startswith(signature):
            return kind

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    head = data[:_SVG_PROBE].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<svg", b"<?xml", b"<!--", b"<!doctype svg")) and b"<svg" in head:
        return "image/svg+xml"

    return "application/octet-stream"


def describe(
    placed: PlacedObject,
    blocks: Sequence[ParsedBlock],
    pictures: dict[ImageSource, Picture],
) -> Described:
    """Содержимое объекта и его сумма."""
    parsed = placed.object
    location = dict(parsed.location)
    if parsed.anchors:
        location["anchors"] = list(parsed.anchors)

    payload = dict(parsed.payload)
    content = [blocks[index] for index in placed.content]

    if parsed.type is ObjectType.FIGURE:
        payload["images"] = [_image_entry(source, pictures.get(source)) for source in parsed.images]
        checksum = _digest([[entry["sha256"], entry["src"]] for entry in payload["images"]])
    elif parsed.type is ObjectType.TABLE:
        checksum = _digest(
            {
                "grid": payload,
                "cells": [
                    [block.location.get("row"), block.location.get("column"), block.text]
                    for block in content
                ],
            }
        )
    elif parsed.type is ObjectType.EQUATION:
        checksum = hashlib.sha256(str(payload.get("raw", "")).encode()).hexdigest()
    else:
        checksum = _digest([block.text for block in content])

    return Described(
        type=parsed.type,
        location=location,
        payload=payload,
        checksum=checksum,
        label=_label(placed, blocks),
    )


def _image_entry(source: ImageSource, picture: Picture | None) -> dict[str, Any]:
    return {
        "sha256": picture.sha256 if picture is not None else None,
        "media_type": picture.media_type if picture is not None else None,
        "size": len(picture.data) if picture is not None else None,
        "src": source.src,
        "alt": source.alt,
    }


def _label(placed: PlacedObject, blocks: Sequence[ParsedBlock]) -> str | None:
    """Номер объекта: из подписи, если она его называет, иначе из самого объекта."""
    if placed.caption is not None:
        label = caption_label(blocks[placed.caption].text)
        if label is not None and label.type is placed.object.type:
            return label.number

    return placed.object.label


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    return hashlib.sha256(payload.encode()).hexdigest()


def picture_key(organization_id: object, sha256: str) -> str:
    """Ключ изображения в хранилище — по содержимому.

    Одна картинка, стоящая в книге дважды, и та же картинка в новой версии
    мастера лежат одним файлом. Файл под ключом не меняется никогда:
    другое содержимое — другой ключ.
    """
    return f"figures/{organization_id}/{sha256[:2]}/{sha256}"
