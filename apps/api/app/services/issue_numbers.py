"""Постоянные коды замечаний и отпечатки находок.

Код `BK01-CH03-ERR-0001` выдаёт только сервер, в той же транзакции, что и запись. Номер не
возвращается после отклонения или закрытия: счётчик только растёт, и код, однажды попавший
в переписку, навсегда указывает на одну запись.
"""

import hashlib
import unicodedata
import uuid

from app.models.book import BookEdition
from app.models.chapter import Chapter
from app.models.coding import CodeKind
from app.services.base import TenantService
from app.services.coding import CodeAllocator
from app.services.errors import ConflictError


class IssueNumberService(TenantService):
    async def allocate(self, book: BookEdition, chapter: Chapter) -> tuple[int, str]:
        """Следующий номер в главе и собранный из него код."""
        if chapter.code is None:
            # Код главы выдаётся при утверждении границ: без него код замечания пришлось бы
            # менять потом, а это ровно то, чего он обещает не делать.
            raise ConflictError("У главы ещё нет кода: сначала утвердите её границы")

        number = await CodeAllocator(self._session, self._context).next(CodeKind.ISSUE, chapter.id)

        return number, f"{book.code}-{chapter.code}-ERR-{number:04d}"


def dedupe_key(
    check: str,
    *,
    block_id: uuid.UUID | None,
    object_id: uuid.UUID | None,
    revision_id: uuid.UUID | None,
    finding: str,
) -> str:
    """Отпечаток находки автоматической проверки.

    Находка та же, если совпали проверка, предмет, редакция и смысл. Пробелы и регистр смысла
    не меняют, а форму Юникода текст мог сменить при сохранении: без приведения одна и та же
    находка получила бы второй код. Новая редакция — уже другая находка: проверяли другой
    текст.
    """
    normal = " ".join(unicodedata.normalize("NFC", finding).casefold().split())
    parts = (check, str(block_id or ""), str(object_id or ""), str(revision_id or ""), normal)

    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
