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
    python -m app.cli check-provider --model claude-opus-5-5
    python -m app.cli check-provider --all-models
"""

import argparse
import asyncio
import getpass
import io
import sys
from collections.abc import Awaitable, Callable

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import generate_password, hash_password
from app.db.session import get_sessionmaker
from app.models.organization import User, UserStatus
from app.services.models import available_models
from app.services.pricing import estimate_usd
from app.services.providers import (
    CLAUDE,
    LookupRequest,
    ProviderError,
    TranslationRequest,
    Usage,
    get_figure_reader,
    get_lookup,
    get_provider,
    get_reviewer,
    keys_of,
)
from app.services.providers.semantic import SemanticRequest

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


async def check_provider(with_lookup: bool, model: str | None = None) -> bool:
    """Пробный вызов модели. Возвращает признак «всё получилось».

    Проверяется именно то, что делает приложение: тот же провайдер, те же
    настройки, тот же разбор ответа. Отдельный «тестовый запрос» мимо
    провайдера проверял бы сам себя.
    """
    settings = get_settings()
    name = model or settings.anthropic_model

    print("Провайдер перевода: " + settings.translation_provider)
    print("Модель:             " + name)
    print("Шлюз:               " + (settings.anthropic_base_url or "нет, напрямую в Anthropic"))
    print("Ключ:               " + _masked(settings.anthropic_api_key))
    print("Поиск справок:      " + settings.term_lookup_provider)
    print()

    if settings.translation_provider != CLAUDE:
        print("Перевод идёт заглушкой: TRANSLATION_PROVIDER=claude включает модель.")
        return True

    provider = get_provider(model)
    requests = _probe_requests()

    print("Пробный перевод…")

    try:
        answer = await provider.translate(requests)
    except ProviderError as error:
        print(f"  ОТКАЗ: {error}")
        return False
    except Exception as error:  # noqa: BLE001 — печатаем любую причину: это и есть проверка
        print(f"  СБОЙ СВЯЗИ: {type(error).__name__}: {error}")
        return False

    for (source, _), key in zip(PROBE, keys_of(requests), strict=True):
        print(f"  {source}\n  → {answer.items[key]}")

    _report_usage(name, answer.usage)

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


def _probe_requests() -> list[TranslationRequest]:
    return [
        TranslationRequest(
            source_text=text,
            source_language="en",
            target_language="ru",
            kind=kind,
        )
        for text, kind in PROBE
    ]


def _probe_picture() -> bytes:
    """Схема с двумя надписями: рисунок, который есть что прочитать."""
    image = Image.new("RGB", (640, 320), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=32)
    draw.rectangle((40, 100, 280, 220), outline=(0, 0, 0), width=3)
    draw.rectangle((360, 100, 600, 220), outline=(0, 0, 0), width=3)
    draw.line((280, 160, 360, 160), fill=(0, 0, 0), width=3)
    draw.text((70, 140), "Relief valve", fill=(0, 0, 0), font=font)
    draw.text((430, 140), "Pump", fill=(0, 0, 0), font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()


async def _probe_translation(model: str) -> tuple[str, Usage]:
    answer = await get_provider(model).translate(_probe_requests())

    return f"переведено строк: {len(answer.items)}", answer.usage


async def _probe_review(model: str) -> tuple[str, Usage]:
    answer = await get_reviewer(model).review(
        [
            SemanticRequest(
                key="CH01-B0001",
                source_text="Close the valve before removal.",
                target_text="Перед демонтажом откройте клапан.",
                source_language="en",
                target_language="ru",
            )
        ]
    )

    return f"находок: {sum(len(items) for items in answer.items.values())}", answer.usage


async def _probe_figure(model: str) -> tuple[str, Usage]:
    reading = await get_figure_reader(model).read(_probe_picture(), "image/png")

    return f"надписей: {len(reading.regions)}", reading.usage


async def check_all_models() -> bool:
    """Каждая модель каталога: перевод, смысловая сверка и чтение рисунка.

    Имя в каталоге ещё не значит, что шлюз принимает модель и все виды запросов к ней. Запросы идут
    через те же провайдеры, что и работа с книгой. Один отказ не прерывает проверку: нужен весь
    список сразу. Это платно, хотя и копейки: по три коротких запроса на модель.
    """
    if get_settings().translation_provider != CLAUDE:
        print("Перевод идёт заглушкой: TRANSLATION_PROVIDER=claude включает модель.")
        return True

    probes: tuple[tuple[str, Callable[[str], Awaitable[tuple[str, Usage]]]], ...] = (
        ("перевод", _probe_translation),
        ("сверка", _probe_review),
        ("рисунок", _probe_figure),
    )
    all_good = True

    for choice in available_models():
        print(f"{choice.title} ({choice.id})")

        for title, probe in probes:
            try:
                note, usage = await probe(choice.id)
            except Exception as error:  # noqa: BLE001 — печатаем любую причину: это и есть проверка
                all_good = False
                print(f"  {title}: ОТКАЗ: {type(error).__name__}: {error}")
                continue

            spent = estimate_usd(
                choice.id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                cache_write_tokens=usage.cache_write_tokens,
            )
            print(f"  {title}: работает, {note}" + (f", ${spent}" if spent is not None else ""))

    return all_good


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
    # Консоль Windows работает в однобайтовой кодировке, и стрелка «→» в
    # ней невыразима: без этой строки команда падает на печати результата,
    # уже сделав (и оплатив) запрос к модели. Кодировку не меняем — русский
    # в этой консоли выводится верно, — только перестаём падать на знаках,
    # которых в ней нет.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

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

    check.add_argument(
        "--model", default=None, help="Проверить эту модель вместо умолчания площадки"
    )
    check.add_argument(
        "--all-models",
        action="store_true",
        help="Проверить каждую модель каталога: перевод, сверку и рисунок (платно)",
    )

    args = parser.parse_args(argv)

    if args.command == "check-provider":
        if args.all_models:
            return 0 if asyncio.run(check_all_models()) else 1

        return 0 if asyncio.run(check_provider(args.lookup, args.model)) else 1

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
