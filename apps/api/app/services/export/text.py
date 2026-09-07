"""Сборка в текст и в Markdown.

Доступна для любого исходника. Смысл не в том, чтобы заменить формат
оригинала, а в том, чтобы перевод можно было забрать всегда: книга,
разобранная из PDF или EPUB, обратно в тот же вид не собирается, а отдать
результат заказчику нужно в любом случае.

Markdown размечает то, что известно из разбора: заголовки, списки, ячейки
таблиц, предупреждения. Это не восстановление оригинала — это его структура,
записанная так, чтобы её было видно и человеку, и вёрстке.
"""

from pathlib import Path

from app.models.segment import SegmentKind
from app.services.export.base import Rendered, TranslatedBlock

# Уровень заголовка известен только там, где его записал разборщик
# (Markdown). Для остальных форматов уровень один: выдумывать иерархию по
# длине строки или регистру — гадание, а неверная иерархия хуже плоской.
DEFAULT_HEADING_LEVEL = 2


class TextRenderer:
    """Простой текст: абзацы через пустую строку."""

    media_type = "text/plain; charset=utf-8"
    suffix = ".txt"

    @property
    def needs_source(self) -> bool:
        return False

    def render(self, blocks: list[TranslatedBlock], *, source: Path | None = None) -> Rendered:
        body = "\n\n".join(block.text.strip() for block in blocks if block.text.strip())

        return Rendered(
            content=(body + "\n").encode("utf-8"),
            media_type=self.media_type,
            suffix=self.suffix,
        )


class MarkdownRenderer:
    """Markdown: сохраняется структура, известная из разбора."""

    media_type = "text/markdown; charset=utf-8"
    suffix = ".md"

    @property
    def needs_source(self) -> bool:
        return False

    def render(self, blocks: list[TranslatedBlock], *, source: Path | None = None) -> Rendered:
        lines = [self._line(block) for block in blocks if block.text.strip()]
        body = "\n\n".join(line for line in lines if line)

        return Rendered(
            content=(body + "\n").encode("utf-8"),
            media_type=self.media_type,
            suffix=self.suffix,
        )

    @staticmethod
    def _line(block: TranslatedBlock) -> str:
        text = block.text.strip()

        if block.kind is SegmentKind.HEADING:
            level = block.location.get("level")
            depth = (
                int(level) if isinstance(level, int) and 1 <= level <= 6 else DEFAULT_HEADING_LEVEL
            )

            return "#" * depth + " " + text

        if block.kind is SegmentKind.LIST_ITEM:
            return "- " + text

        if block.kind is SegmentKind.CODE:
            return "```\n" + text + "\n```"

        if block.kind is SegmentKind.WARNING:
            # Цитатой: предупреждение обязано быть видно и в исходном тексте
            # файла, а не только после отрисовки.
            return "> " + text.replace("\n", "\n> ")

        if block.kind is SegmentKind.TABLE_CELL:
            # Собрать обратно таблицу по одной ячейке нельзя: сколько в
            # строке колонок, известно только исходнику. Ячейка отдаётся
            # строкой — потеря вёрстки, но не содержимого.
            return "| " + text + " |"

        if block.kind is SegmentKind.CAPTION:
            return "*" + text + "*"

        return text
