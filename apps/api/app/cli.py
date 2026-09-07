"""Служебные команды.

Первый администратор площадки заводится отсюда, и другого пути нет
намеренно. Доступ открывает администратор — значит, первого администратора
кто-то должен создать в обход этого правила, и делать это должен тот, у
кого есть доступ к серверу, а не тот, кто первым нашёл адрес регистрации.

Здесь же — проверка связи с моделью. Настройки провайдера нельзя проверить
чтением конфигурации: ключ бывает просроченным, шлюз — недоступным, модель —
переименованной, и узнать об этом на первой книге заказчика хуже, чем одним
пробным переводом при выкате.

Запуск:

    python -m app.cli create-superuser --email root@example.com
    python -m app.cli check-provider
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import generate_password, hash_password
from app.db.session import get_sessionmaker
from app.models.organization import User, UserStatus
from app.services.pricing import estimate_usd
from app.services.providers import (
    CLAUDE,
    LookupRequest,
    ProviderError,
    TranslationRequest,
    Usage,
    get_lookup,
    get_provider,
)

# Материал для пробного перевода. Две короткие строки с числом, единицей и
# сокращением: этого хватает, чтобы увидеть, что модель отвечает по схеме и
# не трогает то, что трогать нельзя, — и стоит это доли копейки.
PROBE = [
    ("Ball valve DN50, PN16, body material 1.4408.", "paragraph"),
    ("WARNING: depressurize the line before removal.", "warning"),
]


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


def _masked(key: str) -> str:
    """Ключ в отчёте: видно, какой задан, но не видно самого ключа.

    Показывается только начало — оно у ключа опознавательное и не секретное
    («sk-aitunn…»), — и длина. Этого хватает, чтобы отличить рабочий ключ от
    вставленного не тем концом, и не хватает, чтобы им воспользоваться.
    """
    if not key:
        return "не задан (клиент возьмёт из окружения или профиля)"

    return f"{key[:8]}… ({len(key)} знаков)"


async def check_provider(with_lookup: bool) -> bool:
    """Пробный вызов модели. Возвращает признак «всё получилось».

    Проверяется именно то, что делает приложение: тот же провайдер, те же
    настройки, тот же разбор ответа. Отдельный «тестовый запрос» мимо
    провайдера проверял бы сам себя.
    """
    settings = get_settings()

    print("Провайдер перевода: " + settings.translation_provider)
    print("Модель:             " + settings.anthropic_model)
    print("Шлюз:               " + (settings.anthropic_base_url or "нет, напрямую в Anthropic"))
    print("Ключ:               " + _masked(settings.anthropic_api_key))
    print("Поиск справок:      " + settings.term_lookup_provider)
    print()

    if settings.translation_provider != CLAUDE:
        print("Перевод идёт заглушкой: TRANSLATION_PROVIDER=claude включает модель.")
        return True

    provider = get_provider()
    requests = [
        TranslationRequest(
            source_text=text,
            source_language="en",
            target_language="ru",
            kind=kind,
        )
        for text, kind in PROBE
    ]

    print("Пробный перевод…")

    try:
        answer = await provider.translate(requests)
    except ProviderError as error:
        print(f"  ОТКАЗ: {error}")
        return False
    except Exception as error:  # noqa: BLE001 — печатаем любую причину: это и есть проверка
        print(f"  СБОЙ СВЯЗИ: {type(error).__name__}: {error}")
        return False

    for source, translated in zip([text for text, _ in PROBE], answer.texts, strict=True):
        print(f"  {source}\n  → {translated}")

    _report_usage(settings.anthropic_model, answer.usage)

    if not with_lookup:
        return True

    print("\nПробная справка о термине…")

    if settings.term_lookup_provider != CLAUDE:
        print("  Поиск выключен: TERM_LOOKUP_PROVIDER=claude включает его.")
        return True

    try:
        explanation = await get_lookup().lookup(
            LookupRequest(
                source_term="PN16",
                source_language="en",
                target_language="ru",
                sample="Ball valve DN50, PN16, body material 1.4408.",
            )
        )
    except Exception as error:  # noqa: BLE001 — печатаем любую причину: это и есть проверка
        print(f"  СБОЙ: {type(error).__name__}: {error}")
        return False

    if explanation.found:
        print(f"  PN16 → {explanation.suggested_target}")
        print(f"  {explanation.definition}")
        for reference in explanation.references:
            print(f"  · {reference.url}")
    else:
        print(f"  Не найдено: {explanation.definition}")

    _report_usage(settings.anthropic_model, explanation.usage, searches=explanation.searches)

    return True


def _report_usage(model: str, usage: Usage, searches: int = 0) -> None:
    """Расход и его оценка в деньгах.

    Оценка бывает пустой, и это не ошибка: модели, которой нет в
    прейскуранте, показывать нулевую цену нельзя. У шлюза имя модели своё,
    и это как раз тот случай.
    """
    spent = estimate_usd(
        model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        searches=searches,
    )

    print(
        f"  Токены: ввод {usage.input_tokens}, вывод {usage.output_tokens}, "
        f"из кэша {usage.cached_input_tokens}, в кэш {usage.cache_write_tokens}"
        + (f", поисков {searches}" if searches else "")
    )
    print("  Оценка: " + (f"${spent}" if spent is not None else "модели нет в прейскуранте"))


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

    check = commands.add_parser(
        "check-provider", help="Пробный вызов модели: связь, ключ, модель, расход"
    )
    check.add_argument(
        "--lookup",
        action="store_true",
        help="Заодно проверить поиск справок (ходит в интернет и стоит отдельно)",
    )

    args = parser.parse_args(argv)

    if args.command == "check-provider":
        return 0 if asyncio.run(check_provider(args.lookup)) else 1

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
