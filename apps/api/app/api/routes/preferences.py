"""Настройки рабочего пространства — куда сообщать о готовности книги.

Модуль называется не `settings`, хотя маршруты начинаются с `/settings`:
этим словом в приложении зовутся его собственные настройки
(`app.core.config`), и два разных `settings` в одном файле — ровно то
место, где однажды возьмут не тот.
"""

from fastapi import APIRouter

from app.api.deps import ContextDep, SessionDep
from app.models.notification import NotificationSettings
from app.schemas.notification import NotificationSettingsPublic, NotificationSettingsUpdate
from app.services.notify import EmailChannel, NotificationSettingsService, TelegramChannel

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
