"""Выгрузка реестра в CSV и XLSX.

🔥 В ячейки попадает текст книг и то, что написали люди. Начинающаяся со знака `=` строка в
Excel — это формула, и файл реестра, открытый на чужой машине, выполнил бы её. Поэтому в CSV
такие ячейки экранируются апострофом, а в XLSX записываются явно как строка: библиотека иначе
сама сделала бы из них формулу.
"""

import csv
import enum
import io
from collections.abc import Sequence
from datetime import datetime

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from app.models.issue import IssueCategory, IssueSeverity, IssueStatus
from app.services.issues import IssueRow

# Выгрузка собирается в памяти: потолок держит её в разумных пределах.
EXPORT_CEILING = 20_000


class IssueExportFormat(str, enum.Enum):
    CSV = "csv"
    XLSX = "xlsx"


CATEGORY = {
    IssueCategory.TRANSLATION: "Перевод",
    IssueCategory.TERMINOLOGY: "Терминология",
    IssueCategory.SEMANTIC: "Смысл",
    IssueCategory.NUMBER: "Числа",
    IssueCategory.FORMULA: "Формула",
    IssueCategory.TABLE: "Таблица",
    IssueCategory.FIGURE: "Рисунок",
    IssueCategory.CODE: "Код",
    IssueCategory.TECHNICAL: "Техническая",
    IssueCategory.STYLE: "Стиль",
    IssueCategory.CROSS_REFERENCE: "Перекрёстная ссылка",
    IssueCategory.SOURCE_ERROR: "Ошибка оригинала",
    IssueCategory.LAYOUT: "Вёрстка",
}
SEVERITY = {
    IssueSeverity.CRITICAL: "Критичная",
    IssueSeverity.MAJOR: "Серьёзная",
    IssueSeverity.MINOR: "Незначительная",
}
STATUS = {
    IssueStatus.NEW: "Новая",
    IssueStatus.NEEDS_CLARIFICATION: "Нужно уточнение",
    IssueStatus.CONFIRMED: "Подтверждена",
    IssueStatus.FIXED: "Исправлена",
    IssueStatus.VERIFIED: "Проверена",
    IssueStatus.CLOSED: "Закрыта",
    IssueStatus.REJECTED: "Отклонена",
    IssueStatus.REOPENED: "Открыта заново",
}

HEADER = (
    "Код",
    "Книга",
    "Блок",
    "Объект",
    "Категория",
    "Серьёзность",
    "Статус",
    "Приоритет",
    "Оригинал",
    "Перевод",
    "Описание",
    "Предложение",
    "Нашёл",
    "Назначено",
    "Заведено",
)

# Со всего этого Excel и его собратья начинают разбирать формулу.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _rows(items: Sequence[IssueRow]) -> list[tuple[str | int, ...]]:
    def when(moment: datetime) -> str:
        return moment.strftime("%Y-%m-%d %H:%M")

    return [
        (
            row.issue.code,
            row.book_title,
            row.block_code or "",
            row.object_code or "",
            CATEGORY[row.issue.category],
            SEVERITY[row.issue.severity],
            STATUS[row.issue.status],
            row.issue.priority_score,
            row.issue.source_snapshot,
            row.issue.target_snapshot or "",
            row.issue.description,
            row.issue.proposed_fix or "",
            row.detected_by or ("проверка" if row.issue.automatic else ""),
            row.assignee or "",
            when(row.issue.created_at),
        )
        for row in items
    ]


def _safe_csv(value: str | int) -> str | int:
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value

    return value


def to_csv(items: Sequence[IssueRow]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(HEADER)

    for row in _rows(items):
        writer.writerow([_safe_csv(value) for value in row])

    # Метка порядка байтов нужна Excel: без неё он читает кириллицу в локальной кодировке.
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(items: Sequence[IssueRow]) -> bytes:
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Реестр ошибок")
    sheet.append(list(HEADER))

    for row in _rows(items):
        cells = []
        for value in row:
            if isinstance(value, str):
                # Управляющие знаки формат не допускает: библиотека на них падает.
                cell = WriteOnlyCell(sheet, value=ILLEGAL_CHARACTERS_RE.sub("", value))
                cell.data_type = "s"
            else:
                cell = WriteOnlyCell(sheet, value=value)
            cells.append(cell)
        sheet.append(cells)

    buffer = io.BytesIO()
    book.save(buffer)

    return buffer.getvalue()


MEDIA_TYPES = {
    IssueExportFormat.CSV: "text/csv; charset=utf-8",
    IssueExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
