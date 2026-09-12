"""Общий словарь площадки: лента загрузок, одобрение и подсказки.

Две стороны у одного словаря.

Сторона площадки — администратор. Он видит ленту загрузок всех
пространств: кто, когда, какой файл и сколько терминов принёс. Состав
загрузки и кнопка «в общий словарь» открыты только там, где пространство
дало разрешение; без него виден факт загрузки и числа, но не слова.

Сторона пространства — подсказки. Термины общего словаря по тематике
пространства, которых в его словаре нет, показываются списком с кнопкой
«принять»; принятый становится своим термином. В перевод они попадают и
без принятия — необязательными рекомендациями (см. `GlossaryService.load`).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import GlossaryTerm, GlossaryTermStatus, GlossaryUpload
from app.models.organization import Organization, User
from app.models.project import Project
from app.models.shared import SharedTerm
from app.models.workspace import WorkspaceSettings
from app.services.base import TenantService
from app.services.errors import AccessDeniedError, InvalidInputError, NotFoundError
from app.services.glossary import PLATFORM, GlossaryService
from app.services.search import ESCAPE, contains
from app.services.subjects import is_subject
from app.services.workspace import subject_for

# Сколько подсказок отдавать пространству за раз. Больше никто не
# читает, а принятые уходят из списка и освобождают место следующим.
SUGGESTION_LIMIT = 200


@dataclass(slots=True)
class UploadCard:
    """Загрузка в ленте администратора — с тем, что нужно, чтобы её понять."""

    upload: GlossaryUpload
    organization_name: str
    uploaded_by: str | None
    # Тематика пространства: с ней термины и предлагаются в общий словарь.
    subject: str | None
    reviewed_by: str | None


@dataclass(slots=True)
class SharedPage:
    total: int
    items: list[SharedTerm]


class SharedGlossaryService:
    """Действия администратора площадки.

    Права проверяются на входе в обработчик, а не здесь: сервис не привязан
    к организации и должен оставаться вызываемым из консоли.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def uploads(
        self, *, unreviewed_only: bool = False, limit: int = 100, offset: int = 0
    ) -> list[UploadCard]:
        """Лента загрузок всех пространств: непросмотренные первыми, новые выше."""
        statement = (
            select(GlossaryUpload, Organization.name, WorkspaceSettings.subject)
            .join(Organization, Organization.id == GlossaryUpload.organization_id)
            .outerjoin(
                WorkspaceSettings,
                WorkspaceSettings.organization_id == GlossaryUpload.organization_id,
            )
        )

        if unreviewed_only:
            statement = statement.where(GlossaryUpload.reviewed_at.is_(None))

        statement = (
            statement.order_by(
                GlossaryUpload.reviewed_at.is_not(None), GlossaryUpload.created_at.desc()
            )
            .limit(limit)
            .offset(offset)
        )

        rows = (await self._session.execute(statement)).all()
        people = await self._emails(
            [row[0].uploaded_by_id for row in rows] + [row[0].reviewed_by_id for row in rows]
        )

        return [
            UploadCard(
                upload=upload,
                organization_name=name,
                uploaded_by=people.get(upload.uploaded_by_id),
                subject=subject,
                reviewed_by=people.get(upload.reviewed_by_id),
            )
            for upload, name, subject in rows
        ]

    async def unreviewed_count(self) -> int:
        counted = await self._session.scalar(
            select(func.count())
            .select_from(GlossaryUpload)
            .where(GlossaryUpload.reviewed_at.is_(None))
        )

        return int(counted or 0)

    async def upload(self, upload_id: uuid.UUID) -> UploadCard:
        cards = await self._cards_by_id([upload_id])
        if not cards:
            raise NotFoundError("Загрузка не найдена")

        return cards[0]

    async def upload_terms(self, upload_id: uuid.UUID) -> list[GlossaryTerm]:
        """Термины загрузки — только если пространство разрешило их отдать.

        Отказ здесь — не про права администратора, а про чужие данные:
        словарь заказчика содержит его решения, иногда про внутренние
        стандарты и названия продукции. Без разрешения он остаётся его.
        """
        card = await self.upload(upload_id)

        if not card.upload.shared:
            raise AccessDeniedError("Пространство не разрешило использовать этот словарь")

        rows = await self._session.scalars(
            select(GlossaryTerm)
            .where(
                GlossaryTerm.upload_id == upload_id,
                GlossaryTerm.status != GlossaryTermStatus.RETIRED,
            )
            .order_by(GlossaryTerm.source_term_normalized)
        )

        return list(rows)

    async def publish(self, term_ids: Sequence[uuid.UUID], *, subject: str, by: User) -> int:
        """Одобрить термины в общий словарь под тематикой.

        Берутся только термины из загрузок с разрешением — проверка на
        стороне базы, а не по списку идентификаторов, чтобы подделанный
        запрос не вынес чужой словарь. Повторное одобрение того же слова
        уточняет перевод, а не заводит второй.
        """
        if not is_subject(subject):
            raise InvalidInputError(f"Тематики «{subject}» нет в списке")

        if not term_ids:
            return 0

        rows = list(
            await self._session.scalars(
                select(GlossaryTerm)
                .join(GlossaryUpload, GlossaryUpload.id == GlossaryTerm.upload_id)
                .where(
                    GlossaryTerm.id.in_(list(term_ids)),
                    GlossaryUpload.shared.is_(True),
                    GlossaryTerm.status != GlossaryTermStatus.RETIRED,
                )
            )
        )

        if not rows:
            return 0

        # Одно слово из двух пространств за раз — одна запись, побеждает
        # последняя: иначе вставка упала бы на «cannot affect row a second
        # time», и не одобрилось бы вообще ничего.
        values = {
            (row.source_language, row.target_language, row.source_term_normalized): {
                "id": uuid.uuid4(),
                "subject": subject,
                "source_language": row.source_language,
                "target_language": row.target_language,
                "source_term": row.source_term,
                "source_term_normalized": row.source_term_normalized,
                "target_term": row.target_term,
                "note": row.note,
                "kind": row.kind,
                "origin_organization_id": row.organization_id,
                "origin_term_id": row.id,
                "approved_by_id": by.id,
            }
            for row in rows
        }

        statement = insert(SharedTerm).values(list(values.values()))
        statement = statement.on_conflict_do_update(
            constraint="shared_term_in_subject",
            set_={
                name: statement.excluded[name]
                for name in (
                    "source_term",
                    "target_term",
                    "note",
                    "kind",
                    "origin_organization_id",
                    "origin_term_id",
                    "approved_by_id",
                )
            },
        )

        await self._session.execute(statement)
        await self._session.commit()

        return len(values)

    async def mark_reviewed(self, upload_id: uuid.UUID, *, by: User) -> UploadCard:
        card = await self.upload(upload_id)

        card.upload.reviewed_at = datetime.now(UTC)
        card.upload.reviewed_by_id = by.id

        await self._session.commit()

        return await self.upload(upload_id)

    async def shared(
        self,
        *,
        subject: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SharedPage:
        statement = select(SharedTerm)

        if subject:
            statement = statement.where(SharedTerm.subject == subject)

        if query:
            pattern = contains(query)
            statement = statement.where(
                or_(
                    SharedTerm.source_term_normalized.ilike(pattern, escape=ESCAPE),
                    SharedTerm.target_term.ilike(pattern, escape=ESCAPE),
                )
            )

        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = await self._session.scalars(
            statement.order_by(SharedTerm.subject, SharedTerm.source_term_normalized)
            .limit(limit)
            .offset(offset)
        )

        return SharedPage(total=int(total or 0), items=list(rows))

    async def remove(self, shared_id: uuid.UUID) -> None:
        term = await self._session.get(SharedTerm, shared_id)
        if term is None:
            raise NotFoundError("Запись общего словаря не найдена")

        await self._session.delete(term)
        await self._session.commit()

    async def _cards_by_id(self, ids: Sequence[uuid.UUID]) -> list[UploadCard]:
        rows = (
            await self._session.execute(
                select(GlossaryUpload, Organization.name, WorkspaceSettings.subject)
                .join(Organization, Organization.id == GlossaryUpload.organization_id)
                .outerjoin(
                    WorkspaceSettings,
                    WorkspaceSettings.organization_id == GlossaryUpload.organization_id,
                )
                .where(GlossaryUpload.id.in_(list(ids)))
            )
        ).all()
        people = await self._emails(
            [row[0].uploaded_by_id for row in rows] + [row[0].reviewed_by_id for row in rows]
        )

        return [
            UploadCard(
                upload=upload,
                organization_name=name,
                uploaded_by=people.get(upload.uploaded_by_id),
                subject=subject,
                reviewed_by=people.get(upload.reviewed_by_id),
            )
            for upload, name, subject in rows
        ]

    async def _emails(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        wanted = {value for value in ids if value is not None}
        if not wanted:
            return {}

        rows = await self._session.execute(
            select(User.id, User.email).where(User.id.in_(list(wanted)))
        )

        return {row[0]: row[1] for row in rows.all()}


@dataclass(slots=True)
class Suggestions:
    # Тематика пространства; пусто — подсказок нет, и витрина зовёт в
    # настройки, а не показывает пустой список без объяснения.
    subject: str | None
    items: list[SharedTerm]


class SuggestionService(TenantService):
    """Подсказки из общего словаря — глазами пространства."""

    async def suggest(self, *, limit: int = SUGGESTION_LIMIT) -> Suggestions:
        subject = await subject_for(self._session, self.organization_id)
        if subject is None:
            return Suggestions(subject=None, items=[])

        pairs = (
            await self._session.execute(
                self.scoped(Project)
                .with_only_columns(Project.source_language, Project.target_language)
                .distinct()
            )
        ).all()
        if not pairs:
            return Suggestions(subject=subject, items=[])

        # Что в словаре уже есть — по общим для пространства записям: своё
        # решение делает подсказку ненужной, а снятое — нет.
        own = {
            (row[0], row[1], row[2])
            for row in (
                await self._session.execute(
                    self.scoped(GlossaryTerm)
                    .with_only_columns(
                        GlossaryTerm.source_language,
                        GlossaryTerm.target_language,
                        GlossaryTerm.source_term_normalized,
                    )
                    .where(
                        GlossaryTerm.project_id.is_(None),
                        GlossaryTerm.status != GlossaryTermStatus.RETIRED,
                    )
                )
            ).all()
        }

        rows = await self._session.scalars(
            select(SharedTerm)
            .where(
                SharedTerm.subject == subject,
                tuple_(SharedTerm.source_language, SharedTerm.target_language).in_(
                    [(source, target) for source, target in pairs]
                ),
            )
            .order_by(SharedTerm.source_term_normalized)
            .limit(limit + len(own))
        )

        items = [
            row
            for row in rows
            if (row.source_language, row.target_language, row.source_term_normalized) not in own
        ]

        return Suggestions(subject=subject, items=items[:limit])

    async def accept(self, shared_id: uuid.UUID) -> GlossaryTerm:
        """Принять подсказку: она становится своим подтверждённым термином.

        Тематика при этом не проверяется: человек видел термин и решил, что
        он подходит, — это и есть решение словаря.
        """
        shared = await self._session.get(SharedTerm, shared_id)
        if shared is None:
            raise NotFoundError("Такой подсказки уже нет")

        return await GlossaryService(self._session, self._context).add(
            source_term=shared.source_term,
            target_term=shared.target_term,
            source_language=shared.source_language,
            target_language=shared.target_language,
            note=shared.note,
            kind=shared.kind,
            source=PLATFORM,
            reference="общий словарь площадки",
        )
