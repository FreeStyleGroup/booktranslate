"""Уведомления о готовности книги.

Человек ставит книгу в очередь и уходит. Значит, работа кончается не
переводом, а сообщением о том, что перевод кончился, — иначе фоновый
перевод ничем не лучше вкладки, в которую надо заглядывать.

Почта работает: письмо уходит через ящик площадки. Телеграм — нет, бот ещё
не сделан, и канал говорит об этом отказом с причиной.

🔥 Правило, общее для всех каналов: **никто не имеет права показать
«уведомление отправлено», пока его никто не отправлял.** Отчёт о работе,
которой не было, хуже отсутствия отчёта — по нему перестают проверять.
Поэтому у доставки есть и признак «ушло», и причина, по которой не ушло, а
не один на двоих.

🔥 Про Телеграм. Бот будет один на всю площадку, и ключ его лежит в
настройках площадки, а не в базе: заводить каждому заказчику своего бота
значило бы хранить чужие ключи. Человек указывает у себя только ник.

Из этого следует ограничение, которое видно и в интерфейсе: **бот не может
написать человеку по нику.** Телеграму нужен номер разговора, а тот
появляется только после того, как человек сам напишет боту. Пока номера
нет, отправить некуда — и сказать это надо заранее, а не молчать.
"""

import asyncio
import logging
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.notification import NotificationSettings
from app.models.organization import Role
from app.services.base import TenantService

logger = logging.getLogger(__name__)

EMAIL = "email"
TELEGRAM = "telegram"

# Порт защищённого SMTP: соединение шифруется сразу, без команды перехода.
# На всех остальных портах шифрование включается через STARTTLS.
SMTPS_PORT = 465

# Канал уведомлений общий на всё пространство, и вписанный в него чужой ник
# получит названия всех книг заказчика. Это распоряжение доступом, а не
# работа с текстом, — поэтому только те, кто им и распоряжается.
SETTINGS_ROLES = (Role.ADMIN,)


def clean_username(value: str | None) -> str | None:
    """Ник так, как его хранить.

    «Собачка» снимается: она часть записи, а не имени, и сохранённая
    приведёт к тому, что «@ivanov» однажды не совпадёт с «ivanov».
    """
    return (value or "").strip().lstrip("@").strip() or None


def _clean(value: str | None) -> str | None:
    """Пустая строка из формы — это «не задано», а не значение."""
    return (value or "").strip() or None


def _addresses(settings: NotificationSettings, requested_by: str | None) -> list[str]:
    """Кому уходит письмо о готовности книги.

    Первым — заказчик перевода: он единственный, про кого точно известно,
    что он этой книги ждёт, и почта его учётной записи уже проверена при
    входе. Вторым — общий адрес пространства, если его завели.

    Совпадающие адреса схлопываются: письмо, пришедшее дважды, выглядит
    как сбой, а не как забота. Порядок при этом сохраняется — по нему
    видно, кому сообщение адресовано в первую очередь.
    """
    chosen: list[str] = []

    for address in ((requested_by or "").strip(), (settings.email_extra or "").strip()):
        if address and address.casefold() not in {item.casefold() for item in chosen}:
            chosen.append(address)

    return chosen


@dataclass(frozen=True, slots=True)
class Message:
    """Готовое сообщение.

    Один текст на все каналы: сообщать они обязаны об одном и том же, а
    разная формулировка в письме и в чате означала бы два разных
    представления о том, что случилось.
    """

    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class Delivery:
    """Что стало с одной попыткой отправки."""

    channel: str
    # Куда собирались слать: адрес или ник. Пусто — было некуда.
    to: str
    sent: bool
    # Почему не отправлено — или чем отправлено, когда заработает.
    detail: str


def ready_message(*, title: str, document_id: uuid.UUID, translated: int, flagged: int) -> Message:
    """Текст о готовой книге.

    Без похвалы и без «успешно»: сообщается то, что человеку нужно решить
    дальше — сколько сегментов ждёт его глазами и куда идти.
    """
    where = f"{get_settings().web_url.rstrip('/')}/app/documents/{document_id}"

    if flagged == 0:
        verdict = "Проверки ни к чему не придрались."
    else:
        verdict = (
            f"Проверки отметили {flagged} — числа, термины или подстановки "
            "разошлись с исходником. Это не приговор переводу, а список мест, "
            "на которые стоит посмотреть."
        )

    return Message(
        subject=f"Книга «{title}» переведена",
        body=(
            f"Книга «{title}» переведена: {translated} сегментов.\n{verdict}\n\nОткрыть: {where}"
        ),
    )


class EmailChannel:
    """Почта — через ящик площадки.

    Отправка синхронной библиотекой в отдельном потоке, а не асинхронным
    почтовым клиентом: письмо здесь одно на книгу, то есть одно на часы
    работы, и тащить ради него зависимость незачем. `smtplib` входит в
    Python, а поток не даёт ему заблокировать рабочего.

    Письмо простым текстом. Уведомление о готовности — это три строки и
    ссылка; HTML добавил бы к ним вёрстку, вопрос тёмной темы в почтовом
    клиенте и повод для спам-фильтра.
    """

    name = EMAIL

    @classmethod
    def ready(cls) -> bool:
        """Настроена ли отправка.

        Спрашивается витриной: канал, включённый в настройках, но не
        настроенный на сервере, обязан объявить себя неработающим, а не
        молчать.
        """
        settings = get_settings()

        return bool(settings.smtp_host and settings.smtp_from)

    async def send(self, to: str, message: Message) -> Delivery:
        if not self.ready():
            return Delivery(
                channel=EMAIL,
                to=to,
                sent=False,
                detail="Почта не настроена на сервере: не задан SMTP_HOST",
            )

        settings = get_settings()

        try:
            await asyncio.to_thread(self._deliver, to, message, settings)
        except (OSError, smtplib.SMTPException) as error:
            # Причина уходит человеку целиком: «не отправилось» без причины
            # он всё равно принесёт в поддержку, только без подробностей.
            logger.warning("Письмо на %s не ушло: %s", to, error)

            return Delivery(channel=EMAIL, to=to, sent=False, detail=str(error))

        logger.info("Письмо на %s отправлено: %s", to, message.subject)

        return Delivery(
            channel=EMAIL, to=to, sent=True, detail=f"отправлено через {settings.smtp_host}"
        )

    @staticmethod
    def _deliver(to: str, message: Message, settings: Settings) -> None:
        """Собрать письмо и отдать его почтовому серверу.

        Отдельным методом и без асинхронности: это единственное место,
        которое блокирует поток, и запускается оно через `to_thread`.
        """
        letter = EmailMessage()
        letter["Subject"] = message.subject
        letter["From"] = formataddr((settings.smtp_from_name, settings.smtp_from))
        letter["To"] = to
        # Ответить на уведомление некому, и почтовые клиенты обязаны об
        # этом знать: без заголовка человек ответит в пустоту.
        letter["Auto-Submitted"] = "auto-generated"
        letter.set_content(message.body)

        timeout = settings.smtp_timeout_seconds
        connect = smtplib.SMTP_SSL if settings.smtp_port == SMTPS_PORT else smtplib.SMTP

        with connect(settings.smtp_host, settings.smtp_port, timeout=timeout) as server:
            if settings.smtp_port != SMTPS_PORT:
                # 587 и прочие: соединение открытое, шифрование включается
                # командой. Без неё пароль уходит по сети как есть.
                server.starttls()

            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)

            server.send_message(letter)


class TelegramChannel:
    """Телеграм. Бот ещё не сделан.

    Когда он появится, отправка сведётся к одному запросу — но только для
    тех, у кого известен номер разговора: по нику Телеграм писать не даёт.
    """

    name = TELEGRAM

    @classmethod
    def ready(cls) -> bool:
        return False

    async def send(self, to: str, message: Message) -> Delivery:
        logger.info("Уведомление в Телеграм, %s: %s", to, message.body)

        return Delivery(channel=TELEGRAM, to=to, sent=False, detail="Бот площадки ещё не сделан")


class NotificationSettingsService(TenantService):
    """Настройки уведомлений глазами человека.

    Заводить их заранее незачем: пространство без настроек — это
    пространство, которое ни о чём не просило. Строка появляется при первой
    записи.
    """

    async def load(self) -> NotificationSettings | None:
        settings: NotificationSettings | None = await self._session.scalar(
            select(NotificationSettings).where(
                NotificationSettings.organization_id == self.organization_id
            )
        )

        return settings

    async def save(
        self,
        *,
        email_enabled: bool,
        email_extra: str | None,
        telegram_enabled: bool,
        telegram_username: str | None,
    ) -> NotificationSettings:
        """Записать настройки.

        Настраивать уведомления пространства — дело того, кто им
        распоряжается: канал общий, и вписанный в него чужой ник получит
        названия всех книг заказчика.

        Сменившийся ник сбрасывает номер разговора: он принадлежал прежнему
        человеку, и слать по нему новому — это отправить чужую переписку не
        тому. Номер появится заново, когда новый напишет боту.
        """
        self._context.require(*SETTINGS_ROLES)

        settings = await self.load()

        if settings is None:
            settings = NotificationSettings(organization_id=self.organization_id)
            self._session.add(settings)

        username = clean_username(telegram_username)

        if username != settings.telegram_username:
            settings.telegram_chat_id = None

        settings.email_enabled = email_enabled
        settings.email_extra = _clean(email_extra)
        settings.telegram_enabled = telegram_enabled
        settings.telegram_username = username

        await self._session.commit()
        await self._session.refresh(settings)

        return settings


class NotificationService:
    """Куда и что сообщать. Настройки берутся у рабочего пространства.

    Без контекста запроса: уведомление отправляет фоновый рабочий, у
    которого запроса нет, а организация известна по заданию.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def settings_for(self, organization_id: uuid.UUID) -> NotificationSettings | None:
        settings: NotificationSettings | None = await self._session.scalar(
            select(NotificationSettings).where(
                NotificationSettings.organization_id == organization_id
            )
        )

        return settings

    async def notify(
        self,
        organization_id: uuid.UUID,
        message: Message,
        *,
        requested_by_email: str | None = None,
    ) -> list[Delivery]:
        """Разослать сообщение по включённым каналам.

        Отключённый канал не «молча пропускается», а не возвращается вовсе:
        список доставок — это отчёт о попытках, и строка про канал, который
        никто не включал, засоряла бы его без пользы.

        Пустой список означает ровно одно: сообщать некуда. Тот, кто его
        получил, обязан сказать это человеку, а не считать, что уведомление
        ушло.
        """
        settings = await self.settings_for(organization_id)

        if settings is None:
            return []

        deliveries: list[Delivery] = []

        if settings.email_enabled:
            channel = EmailChannel()

            for address in _addresses(settings, requested_by_email):
                deliveries.append(await channel.send(address, message))

            if not deliveries:
                deliveries.append(Delivery(EMAIL, "", False, "Почта включена, но адреса нет"))

        if settings.telegram_enabled:
            deliveries.append(await self._telegram(settings, message))

        return deliveries

    @staticmethod
    async def _telegram(settings: NotificationSettings, message: Message) -> Delivery:
        """Телеграм: три разных «не отправлено», и путать их нельзя.

        Ник не указан — человек включил канал и не дописал. Номер разговора
        неизвестен — человек ещё не написал боту, и это чинится им, а не
        нами. И только третье — что самой отправки пока нет.
        """
        username = settings.telegram_username

        if not username:
            return Delivery(TELEGRAM, "", False, "Телеграм включён, но ник не указан")

        if not settings.telegram_chat_id:
            return Delivery(
                TELEGRAM,
                f"@{username}",
                False,
                "Телеграм не даёт писать по нику: напишите боту, и адрес определится сам",
            )

        return await TelegramChannel().send(f"@{username}", message)
