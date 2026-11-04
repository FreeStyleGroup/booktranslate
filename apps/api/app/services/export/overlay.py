"""Перерисовка надписей поверх копии изображения.

Берётся байтовая копия оригинала, поверх каждой надписи кладётся заливка цветом фона и
переведённый текст. Файл сохраняется в том же формате, что и оригинал: тогда его можно подставить
и внутрь исходного DOCX или EPUB, не меняя описания файла.

Русский текст обычно длиннее подписи на исходном языке. Если он не помещается даже мелким шрифтом,
это не прячется: надпись помечается, и такой перевод без человека не пройдёт.
"""

import io
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.services.export.base import ExportError

# Предел размера картинки: файл чужой, и маленький PNG распаковывается в гигабайты. Проверяется по
# заголовку, до распаковки. Страница A4 при 600 точках на дюйм — 35 млн точек.
MAX_PIXELS = 40_000_000

# Чем падает разбор чужой картинки: у Pillow это не только его собственная ошибка.
BAD_IMAGE = (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError)

# Только растровые форматы, которые мы сами умеем сохранить обратно.
FORMATS = ("PNG", "JPEG", "WEBP", "GIF")

FONT_PATHS = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
FONT_MIN_PX = 8
# Кегль сверху: подбор идёт сверху вниз, а высота области приходит из ответа модели или формы.
FONT_MAX_PX = 96
LINE_SPACING = 1.15
PADDING_PX = 1

SAVE_OPTIONS: dict[str, dict[str, Any]] = {
    "PNG": {"optimize": True},
    "JPEG": {"quality": 92, "optimize": True},
    "WEBP": {"quality": 92},
    "GIF": {},
}
MEDIA_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


@dataclass(frozen=True, slots=True)
class OverlayText:
    id: str
    x: int
    y: int
    w: int
    h: int
    text: str


@dataclass(frozen=True, slots=True)
class Overlaid:
    content: bytes
    media_type: str
    # Какие надписи не поместились даже самым мелким шрифтом.
    overflow: list[str]


def checked_image(content: bytes) -> Image.Image:
    """Открыть картинку и проверить размер. Распаковка начнётся только после этой проверки."""
    try:
        image = Image.open(io.BytesIO(content), formats=FORMATS)
    except BAD_IMAGE as error:
        raise ExportError("Изображение не читается") from error

    width, height = image.size
    if width * height > MAX_PIXELS:
        image.close()
        raise ExportError(f"Изображение слишком большое: {width}×{height} точек")

    return image


def image_size(content: bytes) -> tuple[int, int]:
    """Размер изображения. Заголовок читается без разбора всей картинки."""
    with checked_image(content) as image:
        return image.size


def overlay(content: bytes, items: list[OverlayText]) -> Overlaid:
    """Новый файл с надписями поверх копии. Оригинальные байты не меняются."""
    try:
        with checked_image(content) as opened:
            original_format = opened.format or "PNG"
            image = opened.convert("RGB")
    except BAD_IMAGE as error:
        raise ExportError("Изображение не читается") from error

    if original_format not in SAVE_OPTIONS:
        raise ExportError(f"Формат изображения {original_format} не поддерживается")

    font_path = _font_path()
    draw = ImageDraw.Draw(image)
    overflow: list[str] = []

    for item in items:
        box = _clamp(item, image.size)
        if box is None:
            overflow.append(item.id)
            continue

        background = _background(image, box)
        draw.rectangle(box, fill=background)

        if not _write(draw, font_path, item.text, box, _contrast(background)):
            overflow.append(item.id)

    buffer = io.BytesIO()
    image.save(buffer, format=original_format, **SAVE_OPTIONS[original_format])

    return Overlaid(
        content=buffer.getvalue(), media_type=MEDIA_TYPES[original_format], overflow=overflow
    )


def _font_path() -> str:
    for candidate in FONT_PATHS:
        if Path(candidate).exists():
            return candidate

    raise ExportError("На сервере нет шрифта с кириллицей")


def _clamp(item: OverlayText, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    width, height = size
    left = max(0, item.x)
    top = max(0, item.y)
    right = min(width - 1, item.x + item.w)
    bottom = min(height - 1, item.y + item.h)

    if right <= left or bottom <= top:
        return None

    return left, top, right, bottom


def _background(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Цвет фона: самый частый на рамке вокруг надписи, внутри неё лежат буквы."""
    left, top, right, bottom = box
    colours: Counter[tuple[int, int, int]] = Counter()

    for x in range(left, right + 1):
        colours[image.getpixel((x, top))] += 1  # type: ignore[index]
        colours[image.getpixel((x, bottom))] += 1  # type: ignore[index]
    for y in range(top, bottom + 1):
        colours[image.getpixel((left, y))] += 1  # type: ignore[index]
        colours[image.getpixel((right, y))] += 1  # type: ignore[index]

    return colours.most_common(1)[0][0]


def _contrast(colour: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = colour
    brightness = 0.299 * red + 0.587 * green + 0.114 * blue

    return (0, 0, 0) if brightness > 140 else (255, 255, 255)


def _write(
    draw: ImageDraw.ImageDraw,
    font_path: str,
    text: str,
    box: tuple[int, int, int, int],
    colour: tuple[int, int, int],
) -> bool:
    """Подобрать кегль и написать. Ложь — не поместилось: текст всё равно пишется самым мелким."""
    left, top, right, bottom = box
    width = right - left - 2 * PADDING_PX
    height = bottom - top - 2 * PADDING_PX
    size = max(FONT_MIN_PX, min(height, FONT_MAX_PX))
    lines: list[str] = []
    fits = False
    font = ImageFont.truetype(font_path, FONT_MIN_PX)

    while size >= FONT_MIN_PX:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, text, font, width)
        total = int(len(lines) * size * LINE_SPACING)
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)

        if total <= height and widest <= width:
            fits = True
            break

        size -= 1

    line_height = int(max(size, FONT_MIN_PX) * LINE_SPACING)
    y = top + PADDING_PX + max(0, (height - len(lines) * line_height) // 2)

    for line in lines:
        draw.text((left + PADDING_PX, y), line, font=font, fill=colour)
        y += line_height

    return fits


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate

    if current:
        lines.append(current)

    return lines or [text]
