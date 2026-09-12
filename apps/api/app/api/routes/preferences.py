"""Настройки рабочего пространства — куда сообщать о готовности книги.

Модуль называется не `settings`, хотя маршруты начинаются с `/settings`:
этим словом в приложении зовутся его собственные настройки
(`app.core.config`), и два разных `settings` в одном файле — ровно то
место, где однажды возьмут не тот.
"""

from fastapi import APIRouter

from app.api.deps import ContextDep, SessionDep
from app.core.config import get_settings
from app.models.notification import NotificationSettings
from app.models.workspace import WorkspaceSettings
from app.schemas.notification import NotificationSettingsPublic, NotificationSettingsUpdate
from app.schemas.workspace import (
    ModelChoicePublic,
    SubjectPublic,
    WorkspaceSettingsPublic,
    WorkspaceSettingsUpdate,
)
from app.services.models import available_models, default_model
from app.services.notify import EmailChannel, NotificationSettingsService, TelegramChannel
from app.services.providers import CLAUDE
from app.services.subjects import SUBJECTS
from app.services.workspace import WorkspaceSettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def _public(settings: NotificationSettings | None) -> NotificationSettingsPublic:
    """Настройки наружу.

    Готовность каналов спрашивается у них самих, а не пишется здесь: когда
    отправку подключат, ответ API изменится вместе с каналом, и витрина
    перестанет предупреждать сама, без правки витрины.
    """
    if settings is None:
        return NotificationSettingsPublic(
            email_ready=EmailChannel.ready(), telegram_ready=TelegramChannel.ready()
        )

    return NotificationSettingsPublic(
        email_enabled=settings.email_enabled,
        email_extra=settings.email_extra,
        telegram_enabled=settings.telegram_enabled,
        telegram_username=settings.telegram_username,
        # Наружу — сам факт, а не номер разговора: человеку нужно знать,
        # дошёл ли он до бота, а номер ему ни о чём не говорит.
        telegram_linked=settings.telegram_chat_id is not None,
        email_ready=EmailChannel.ready(),
        telegram_ready=TelegramChannel.ready(),
    )


@router.get("/notifications", response_model=NotificationSettingsPublic)
async def read_notifications(
    context: ContextDep, session: SessionDep
) -> NotificationSettingsPublic:
    """Куда сообщать о готовности книги.

    Пространство без настроек отвечает выключенными каналами, а не
    отсутствием: «ещё не настраивали» и «выключено» для читающего одно и то
    же, а лишний отказ заставил бы витрину разбирать два случая вместо
    одного.
    """
    return _public(await NotificationSettingsService(session, context).load())


@router.put("/notifications", response_model=NotificationSettingsPublic)
async def write_notifications(
    payload: NotificationSettingsUpdate, context: ContextDep, session: SessionDep
) -> NotificationSettingsPublic:
    """Записать настройки уведомлений.

    Смена ника сбрасывает связь с ботом: номер разговора принадлежал
    прежнему человеку, и слать по нему новому значит отправить чужую
    переписку не тому.
    """
    settings = await NotificationSettingsService(session, context).save(
        email_enabled=payload.email_enabled,
        email_extra=payload.email_extra,
        telegram_enabled=payload.telegram_enabled,
        telegram_username=payload.telegram_username,
    )

    return _public(settings)


def _workspace(settings: WorkspaceSettings | None) -> WorkspaceSettingsPublic:
    chosen = None if settings is None else settings.translation_model

    return WorkspaceSettingsPublic(
        translation_model=chosen or default_model(),
        chosen_model=chosen,
        default_model=default_model(),
        subject=None if settings is None else settings.subject,
        subjects=[SubjectPublic(id=subject.id, title=subject.title) for subject in SUBJECTS],
        share_glossary=settings is not None and settings.share_glossary,
        models=[
            ModelChoicePublic(
                id=choice.id,
                title=choice.title,
                note=choice.note,
                input_usd=None if choice.price is None else choice.price.input_usd,
                output_usd=None if choice.price is None else choice.price.output_usd,
            )
            for choice in available_models()
        ],
        provider_ready=get_settings().translation_provider == CLAUDE,
    )


@router.get("/workspace", response_model=WorkspaceSettingsPublic)
async def read_workspace(context: ContextDep, session: SessionDep) -> WorkspaceSettingsPublic:
    """Чем переводит пространство и из чего можно выбрать.

    Каталог приходит вместе с ответом: витрина рисует выбор по нему, а не
    по своему списку, который разошёлся бы с прейскурантом при первой
    смене цен.
    """
    return _workspace(await WorkspaceSettingsService(session, context).load())


@router.put("/workspace", response_model=WorkspaceSettingsPublic)
async def write_workspace(
    payload: WorkspaceSettingsUpdate, context: ContextDep, session: SessionDep
) -> WorkspaceSettingsPublic:
    """Записать настройки пространства: модель, тематику, разрешение на
    общий словарь. Меняется только присланное. Модель действует на все
    следующие запуски перевода; уже переведённое остаётся как есть —
    вместе с записанным именем модели."""
    changes = payload.model_dump(exclude_unset=True)

    # Пустая строка для модели и тематики значит то же, что null: витрина
    # шлёт значение поля формы, а у формы «ничего не выбрано» — это пусто.
    for name in ("translation_model", "subject"):
        if name in changes:
            changes[name] = changes[name] or None

    settings = await WorkspaceSettingsService(session, context).save(**changes)

    return _workspace(settings)
