"""Отправка письма о готовности книги.

Без базы и без сети: почтовый сервер подменён, и проверяется то, что
уходит в него, — адреса, тема, обратный адрес и то, что соединение
шифруется. Настоящий SMTP в наборе тестов означал бы письма при каждом
прогоне и отказ на машине без интернета.
"""

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest

from app.core.config import get_settings
from app.services.notify import EmailChannel, Message

LETTER = Message(subject="Книга «Насосы» переведена", body="Готово.\n\nОткрыть: https://x/y")


class FakeServer:
    """Почтовый сервер, который всё записывает и никуда не ходит."""

    def __init__(self, log: dict[str, Any]) -> None:
        self._log = log

    def __enter__(self) -> "FakeServer":
        return self

    def __exit__(self, *_: object) -> None:
        self._log["closed"] = True

    def starttls(self) -> None:
        self._log["starttls"] = True

    def login(self, user: str, password: str) -> None:
        self._log["login"] = (user, password)

    def send_message(self, letter: EmailMessage) -> None:
        self._log["letter"] = letter


@pytest.fixture
def mail(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменённый почтовый сервер и настройки под него."""
    log: dict[str, Any] = {}

    def connect(host: str, port: int, timeout: int) -> FakeServer:
        log["where"] = (host, port, timeout)

        return FakeServer(log)

    monkeypatch.setattr(smtplib, "SMTP_SSL", connect)
    monkeypatch.setattr(smtplib, "SMTP", connect)

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "mail.example.ru")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_user", "no-reply@booktranslate.ru")
    monkeypatch.setattr(settings, "smtp_password", "секрет")
    monkeypatch.setattr(settings, "smtp_from", "no-reply@booktranslate.ru")
    monkeypatch.setattr(settings, "smtp_from_name", "BookTranslate")

    return log


async def test_unconfigured_channel_says_so() -> None:
    """Канал без сервера не молчит и не притворяется отправившим."""
    settings = get_settings()
    before = settings.smtp_host
    settings.smtp_host = ""

    try:
        delivery = await EmailChannel().send("kto@example.com", LETTER)
    finally:
        settings.smtp_host = before

    assert delivery.sent is False
    assert "SMTP_HOST" in delivery.detail


async def test_letter_is_sent_and_addressed_properly(mail: dict[str, Any]) -> None:
    delivery = await EmailChannel().send("kto@example.com", LETTER)

    assert delivery.sent is True
    assert mail["where"] == ("mail.example.ru", 465, get_settings().smtp_timeout_seconds)

    letter = mail["letter"]

    assert letter["To"] == "kto@example.com"
    assert letter["From"] == "BookTranslate <no-reply@booktranslate.ru>"
    assert letter["Subject"] == LETTER.subject
    # Отвечать на уведомление некому, и почтовые клиенты обязаны знать это
    # из письма, а не из адреса отправителя.
    assert letter["Auto-Submitted"] == "auto-generated"
    assert letter.get_content().strip() == LETTER.body


async def test_port_465_does_not_ask_for_starttls(mail: dict[str, Any]) -> None:
    """На 465 соединение шифруется сразу: команда перехода там лишняя."""
    await EmailChannel().send("kto@example.com", LETTER)

    assert "starttls" not in mail
    assert mail["login"] == ("no-reply@booktranslate.ru", "секрет")


async def test_port_587_turns_encryption_on(
    mail: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔥 Без STARTTLS пароль на 587 уходит по сети как есть."""
    monkeypatch.setattr(get_settings(), "smtp_port", 587)

    await EmailChannel().send("kto@example.com", LETTER)

    assert mail["starttls"] is True
    # Шифрование включается ДО входа, иначе защищать уже нечего.
    assert mail["login"] == ("no-reply@booktranslate.ru", "секрет")


async def test_refusal_of_the_mail_server_is_passed_on(
    mail: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Не отправилось» без причины человек всё равно принесёт в поддержку."""

    def refuse(*_: object, **__: object) -> FakeServer:
        raise smtplib.SMTPAuthenticationError(535, b"bad password")

    monkeypatch.setattr(smtplib, "SMTP_SSL", refuse)

    delivery = await EmailChannel().send("kto@example.com", LETTER)

    assert delivery.sent is False
    assert "535" in delivery.detail
