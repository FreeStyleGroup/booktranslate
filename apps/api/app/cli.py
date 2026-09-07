"""Служебные команды.

Первый администратор площадки заводится отсюда, и другого пути нет
намеренно. Доступ открывает администратор — значит, первого администратора
кто-то должен создать в обход этого правила, и делать это должен тот, у
кого есть доступ к серверу, а не тот, кто первым нашёл адрес регистрации.

Запуск:

    python -m app.cli create-superuser --email root@example.com
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.security import generate_password, hash_password
from app.db.session import get_sessionmaker
from app.models.organization import User, UserStatus


async def create_superuser(email: str, password: str | None, full_name: str | None) -> str:
    """Завести администратора площадки либо повысить существующего.

    Повторный запуск на существующей почте не ошибка, а обычный способ
    вернуть себе доступ: запись получает права администратора, состояние
    «действует» и новый пароль.
    """
    normalized = email.strip().lower()
    secret = password or generate_password()

    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == normalized))

        if user is None:
            user = User(email=normalized, full_name=full_name)
            session.add(user)

        user.password_hash = hash_password(secret)
        user.status = UserStatus.ACTIVE
        user.is_superuser = True

        if full_name is not None:
            user.full_name = full_name

        await session.commit()

    return secret


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Служебные команды BookTranslate")
    commands = parser.add_subparsers(dest="command", required=True)

    superuser = commands.add_parser(
        "create-superuser", help="Завести администратора площадки или повысить существующего"
    )
    superuser.add_argument("--email", required=True)
    superuser.add_argument("--full-name", default=None)
    superuser.add_argument(
        "--password",
        default=None,
        help="Если не задан — спросим ввод, а на пустой ответ сгенерируем",
    )

    args = parser.parse_args(argv)

    if args.command == "create-superuser":
        password = args.password

        if password is None and sys.stdin.isatty():
            # Ввод скрытый и без повтора: команда служебная, а опечатку
            # лечит повторный запуск.
            password = getpass.getpass("Пароль (пусто — сгенерировать): ") or None

        secret = asyncio.run(create_superuser(args.email, password, args.full_name))

        if args.password is None:
            print(f"Пароль: {secret}")

        print(f"Администратор площадки готов: {args.email}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
