"""Тематики: по ним общий словарь площадки находит своих.

Термин без тематики опасен: «bank» в банковском словаре и «bank» в книге
про реки — разные слова, и подсказка из чужой области хуже, чем никакой.
Поэтому у записи общего словаря тематика обязательна, а пространство
получает подсказки только по своей.

Список в коде, а не в базе, по той же причине, что и каталог моделей:
он меняется с выкатом, а не рукой администратора, и каждое значение
должно быть понятно тому, кто выбирает его в настройках.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Subject:
    id: str
    title: str


SUBJECTS: tuple[Subject, ...] = (
    Subject("engineering", "Техника и производство"),
    Subject("it", "Информационные технологии"),
    Subject("finance", "Финансы и экономика"),
    Subject("law", "Право и договоры"),
    Subject("medicine", "Медицина и фармацевтика"),
    Subject("science", "Наука и образование"),
    Subject("humanities", "Гуманитарные науки"),
    Subject("fiction", "Художественная литература"),
    Subject("general", "Общая лексика"),
)

_BY_ID = {subject.id: subject for subject in SUBJECTS}


def is_subject(value: str) -> bool:
    return value in _BY_ID


def subject_title(value: str) -> str:
    """Название тематики; неизвестный код возвращается как есть, чтобы
    запись со снятой из списка тематикой не пропала из виду."""
    subject = _BY_ID.get(value)

    return value if subject is None else subject.title
