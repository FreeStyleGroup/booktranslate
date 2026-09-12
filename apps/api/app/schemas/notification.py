"""Схемы настроек уведомлений.

Ключа бота здесь нет и быть не может: бот один на всю площадку и живёт в её
настройках. Заказчик указывает только ник — и тем самым не доверяет нам
ничего, чем можно было бы воспользоваться.

🔥 Проверка на кириллицу — не придирка. Почтовый адрес и ник в Телеграме
набирают латиницей, и самая частая ошибка при этом — забытая раскладка:
«ivanov» превращается в «швфтщм». Строка выглядит правдоподобно, форма её
принимает, письмо уходит в никуда, и человек месяц ждёт уведомлений,
которые не придут. Отличить это от опечатки потом невозможно, а поймать
сразу — одна строка.
"""

import re

from pydantic import BaseModel, Field, field_validator

# Годный адрес: что-то, собака, что-то с точкой. Не полная проверка по
# RFC — та принимает и то, чего почтовые серверы не примут, — а отсев
# явного мусора до того, как он попадёт в базу.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# Ник в Телеграме: латиница, цифры и подчёркивание, от пяти знаков.
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def _no_cyrillic(value: str, what: str) -> None:
    if _CYRILLIC.search(value):
        raise ValueError(f"{what} набран русскими буквами — похоже, раскладка была не та")


class NotificationSettingsPublic(BaseModel):
    """Куда сообщать о готовности книги."""

    email_enabled: bool = False
    # Не «кому», а «кому ещё»: письмо и так уходит тому, кто поставил книгу
    # в очередь, — на почту его учётной записи.
    email_extra: str | None = None

    telegram_enabled: bool = False
    # Ник без «собачки»: она часть записи, а не имени.
    telegram_username: str | None = None

    # Написал ли человек боту. Пока нет — Телеграм не даст ему написать:
    # по нику отправлять нельзя, нужен номер разговора, а он появляется
    # только после первого обращения человека к боту.
    telegram_linked: bool = False

    # Отправка ещё не подключена, и витрина обязана об этом сказать.
    # Полем, а не текстом в разметке: когда канал заработает, интерфейс
    # перестанет предупреждать сам, без правки витрины.
    email_ready: bool = False
    telegram_ready: bool = False


class NotificationSettingsUpdate(BaseModel):
    """Запись настроек."""

    email_enabled: bool = False
    email_extra: str | None = Field(default=None, max_length=320)

    telegram_enabled: bool = False
    # С «собачкой» или без — принимается и то и другое, хранится без неё.
    # Потолок в 33 знака: ник Телеграма не длиннее 32 плюс «@».
    telegram_username: str | None = Field(default=None, max_length=33)

    @field_validator("email_extra")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        """Второй адрес — необязательный, но если он есть, он обязан быть годным.

        Пустая строка из формы означает «не задано», а не «пустой адрес»:
        поле, которое человек не заполнил, приходит именно так.
        """
        address = (value or "").strip()

        if not address:
            return None

        _no_cyrillic(address, "Адрес почты")

        if not _EMAIL.match(address):
            raise ValueError("Это не похоже на адрес почты: нужен вид имя@домен.зона")

        return address

    @field_validator("telegram_username")
    @classmethod
    def check_username(cls, value: str | None) -> str | None:
        """Ник — латиница, цифры и подчёркивание; «собачка» необязательна."""
        username = (value or "").strip().lstrip("@").strip()

        if not username:
            return None

        _no_cyrillic(username, "Ник")

        if not _USERNAME.match(username):
            raise ValueError(
                "Ник в Телеграме — от 5 знаков: латиница, цифры и подчёркивание, первый знак буква"
            )

        return username
