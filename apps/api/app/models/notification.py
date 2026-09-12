"""Куда сообщать о готовности книги.

Настройка рабочего пространства, а не человека: книгу ставит в очередь
один, а ждёт её обычно вся команда, и общий канал — чат или рабочий ящик —
это то, как об этом узнают на самом деле.

🔥 Про Телеграм. Бот один на всю площадку и живёт в её настройках; человек
указывает у себя только ник. Заводить каждому заказчику своего бота значило
бы хранить чужие ключи — власть над чужим ботом в нашей базе.

Из-за этого у настроек два поля вместо одного. Ник — то, что человек
вводит. `telegram_chat_id` — то, что подставляет система: **бот не может
написать человеку по нику**, ему нужен номер разговора, а тот появляется
только после того, как человек сам напишет боту. Пока номера нет, отправить
некуда, и интерфейс обязан сказать это, а не молча ничего не слать.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKey


class NotificationSettings(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "notification_settings"

    # Не TenantMixin: у настроек не «принадлежность организации», а
    # отношение один к одному с ней, и это ограничение обязано стоять в
    # базе — двух наборов настроек у одного пространства быть не может.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Письмо всегда уходит тому, кто поставил книгу в очередь, — на почту
    # его учётной записи. Она уже известна и проверена при входе, и
    # заставлять вписывать её второй раз значит завести второе место, где
    # её можно опечатать.
    #
    # Здесь — второй адрес, если он нужен: общий ящик бюро, менеджер
    # проекта, почтовый список. Пусто — письмо уйдёт только заказчику
    # перевода.
    email_extra: Mapped[str | None] = mapped_column(String(320))

    telegram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Ник так, как его вводит человек, — без «собачки»: она часть записи, а
    # не имени, и хранить её значит однажды сравнить «@ivanov» с «ivanov» и
    # не найти. Длина — потолок Телеграма.
    telegram_username: Mapped[str | None] = mapped_column(String(32))

    # Номер разговора с ботом. Заполняет система, а не человек: узнать его
    # неоткуда, пока человек не написал боту сам.
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
