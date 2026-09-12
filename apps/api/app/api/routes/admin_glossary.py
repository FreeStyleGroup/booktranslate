"""Общий словарь площадки — глазами администратора.

Лента загрузок всех пространств, состав тех, где пространство дало
разрешение, одобрение терминов в общий словарь и сам общий словарь.
Все обработчики требуют администратора площадки — как и управление
доступом, это не роль в организации.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import SessionDep, SuperuserDep
from app.schemas.glossary import GlossaryTermPublic
from app.schemas.shared import (
    AdminUploadDetail,
    AdminUploadList,
    AdminUploadPublic,
    PublishedPublic,
    PublishRequest,
    SharedListPublic,
    SharedTermPublic,
)
from app.schemas.workspace import SubjectPublic
from app.services.shared_glossary import SharedGlossaryService, UploadCard
from app.services.subjects import SUBJECTS

router = APIRouter(prefix="/admin/glossary", tags=["admin"])


def _subjects() -> list[SubjectPublic]:
    return [SubjectPublic(id=subject.id, title=subject.title) for subject in SUBJECTS]


def _upload(card: UploadCard) -> AdminUploadPublic:
    return AdminUploadPublic(
        id=card.upload.id,
        organization_id=card.upload.organization_id,
        organization_name=card.organization_name,
        uploaded_by=card.uploaded_by,
        filename=card.upload.filename,
        origin=card.upload.origin,
        source_language=card.upload.source_language,
        target_language=card.upload.target_language,
        total=card.upload.total,
        added=card.upload.added,
        updated=card.upload.updated,
        skipped=card.upload.skipped,
        shared=card.upload.shared,
        subject=card.subject,
        reviewed_at=card.upload.reviewed_at,
        reviewed_by=card.reviewed_by,
        created_at=card.upload.created_at,
    )


@router.get("/uploads", response_model=AdminUploadList)
async def list_uploads(
    admin: SuperuserDep,
    session: SessionDep,
    unreviewed: Annotated[bool, Query(description="Только непросмотренные")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUploadList:
    """Кто и какие словари загружал. Непросмотренные первыми: лента
    открывается ради них."""
    service = SharedGlossaryService(session)
    cards = await service.uploads(unreviewed_only=unreviewed, limit=limit, offset=offset)

    return AdminUploadList(
        items=[_upload(card) for card in cards],
        unreviewed=await service.unreviewed_count(),
        subjects=_subjects(),
    )


@router.get("/uploads/{upload_id}", response_model=AdminUploadDetail)
async def read_upload(
    upload_id: uuid.UUID, admin: SuperuserDep, session: SessionDep
) -> AdminUploadDetail:
    """Состав загрузки. Открыт только там, где пространство разрешило:
    без разрешения отказ — словарь заказчика остаётся его."""
    service = SharedGlossaryService(session)
    card = await service.upload(upload_id)
    terms = await service.upload_terms(upload_id)

    return AdminUploadDetail(
        upload=_upload(card),
        terms=[GlossaryTermPublic.model_validate(term) for term in terms],
        subjects=_subjects(),
    )


@router.post("/uploads/{upload_id}/reviewed", response_model=AdminUploadPublic)
async def mark_upload_reviewed(
    upload_id: uuid.UUID, admin: SuperuserDep, session: SessionDep
) -> AdminUploadPublic:
    """Отметить загрузку просмотренной: она уходит из «новых»."""
    card = await SharedGlossaryService(session).mark_reviewed(upload_id, by=admin)

    return _upload(card)


@router.post("/shared", response_model=PublishedPublic)
async def publish_terms(
    payload: PublishRequest, admin: SuperuserDep, session: SessionDep
) -> PublishedPublic:
    """Одобрить термины в общий словарь под тематикой.

    Берутся только термины из загрузок с разрешением — и это проверяет
    база, а не список идентификаторов в запросе.
    """
    published = await SharedGlossaryService(session).publish(
        payload.term_ids, subject=payload.subject, by=admin
    )

    return PublishedPublic(published=published)


@router.get("/shared", response_model=SharedListPublic)
async def list_shared(
    admin: SuperuserDep,
    session: SessionDep,
    subject: Annotated[str | None, Query(max_length=60)] = None,
    query: Annotated[str | None, Query(max_length=300)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SharedListPublic:
    page = await SharedGlossaryService(session).shared(
        subject=subject, query=query, limit=limit, offset=offset
    )

    return SharedListPublic(
        total=page.total,
        items=[SharedTermPublic.model_validate(item) for item in page.items],
        subjects=_subjects(),
    )


@router.delete("/shared/{shared_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_shared(shared_id: uuid.UUID, admin: SuperuserDep, session: SessionDep) -> Response:
    """Снять запись из общего словаря. У пространств, уже принявших её
    к себе, свой термин остаётся: он их решение, а не наша копия."""
    await SharedGlossaryService(session).remove(shared_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
