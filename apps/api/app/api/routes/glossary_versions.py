"""Версии глоссария книги и гейт терминологии глав."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep
from app.schemas.book_object import BlockRefPublic
from app.schemas.glossary_version import (
    BookTerminologyPublic,
    GateItemPublic,
    GlossaryApproval,
    GlossaryDraftCreate,
    GlossaryVersionDetailPublic,
    GlossaryVersionPublic,
    ImpactedBlockPublic,
    ImpactPagePublic,
    TermChangePublic,
    TerminologyGatePublic,
    TerminologyPassPublic,
    VersionTermPagePublic,
    VersionTermPublic,
)
from app.services.glossary_versions import GlossaryVersionService
from app.services.terminology_gate import Gate, GateItem, TerminologyGate

router = APIRouter(tags=["glossary-versions"])

Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/books/{book_id}/terminology", response_model=BookTerminologyPublic)
async def book_terminology(
    book_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BookTerminologyPublic:
    """Терминология книги: гейт каждой главы и все версии глоссария."""
    gates = await TerminologyGate(session, context).book(book_id)
    versions = await GlossaryVersionService(session, context).of_book(book_id)

    return BookTerminologyPublic(
        chapters=[gate_public(gate) for gate in gates],
        versions=[GlossaryVersionPublic.model_validate(version) for version in versions],
    )


@router.get("/chapters/{chapter_id}/terminology/gate", response_model=TerminologyGatePublic)
async def chapter_terminology_gate(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> TerminologyGatePublic:
    """Готова ли глава к переводу с точки зрения терминов — и что держит.

    У каждой причины свой код: по нему её узнаёт интерфейс и
    автоматический режим, а фраза рядом — для человека.
    """
    return gate_public(await TerminologyGate(session, context).check(chapter_id))


@router.post(
    "/books/{book_id}/glossary-versions",
    response_model=GlossaryVersionPublic,
    status_code=status.HTTP_201_CREATED,
)
async def draft_glossary_version(
    book_id: uuid.UUID, payload: GlossaryDraftCreate, context: ContextDep, session: SessionDep
) -> GlossaryVersionPublic:
    """Собрать черновик версии из рабочего словаря — для книги или одной главы.

    Черновик — неизменяемый снимок: утверждают ровно то, что в нём
    увидели. Прежний черновик той же области заменяется.
    """
    version = await GlossaryVersionService(session, context).create_draft(
        book_id, chapter_id=payload.chapter_id
    )

    return GlossaryVersionPublic.model_validate(version)


@router.get("/glossary-versions/{version_id}", response_model=GlossaryVersionDetailPublic)
async def glossary_version(
    version_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> GlossaryVersionDetailPublic:
    """Версия и то, что надо знать до решения: что мешает утвердить и что изменится."""
    view = await GlossaryVersionService(session, context).view(version_id)

    return GlossaryVersionDetailPublic(
        **GlossaryVersionPublic.model_validate(view.version).model_dump(),
        chapter_code=None if view.chapter is None else view.chapter.code,
        blockers=[_item(item) for item in view.blockers],
        changes=view.changes,
        impacted_blocks=view.impacted,
    )


@router.post("/glossary-versions/{version_id}/approval", response_model=GlossaryVersionPublic)
async def approve_glossary_version(
    version_id: uuid.UUID, payload: GlossaryApproval, context: ContextDep, session: SessionDep
) -> GlossaryVersionPublic:
    """Утвердить черновик: с этого момента по нему переводят.

    Пустую версию утверждают только с основанием — «терминов нет» тоже
    решение. Прежняя действующая версия той же области заменяется, а
    книжная заменяет и версии отдельных глав.
    """
    version = await GlossaryVersionService(session, context).approve(
        version_id, empty_reason=payload.empty_reason
    )

    return GlossaryVersionPublic.model_validate(version)


@router.get("/glossary-versions/{version_id}/terms", response_model=VersionTermPagePublic)
async def glossary_version_terms(
    version_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    query: Annotated[str | None, Query(max_length=300)] = None,
    mandatory: Annotated[bool | None, Query()] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> VersionTermPagePublic:
    """Термины снимка — такими, какими их утвердили."""
    page = await GlossaryVersionService(session, context).terms(
        version_id, query=query, mandatory=mandatory, limit=limit, offset=offset
    )

    return VersionTermPagePublic(
        total=page.total, items=[VersionTermPublic.model_validate(item) for item in page.items]
    )


@router.get("/glossary-versions/{version_id}/changes", response_model=list[TermChangePublic])
async def glossary_version_changes(
    version_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> list[TermChangePublic]:
    """Чем обязательные термины версии отличаются от предыдущей утверждённой."""
    changes = await GlossaryVersionService(session, context).changes(version_id)

    return [
        TermChangePublic(
            id=view.change.id,
            source_term=view.change.source_term,
            kind=view.change.kind,
            before=view.change.before,
            after=view.change.after,
            blocks=view.blocks,
        )
        for view in changes
    ]


@router.get("/glossary-versions/{version_id}/impact", response_model=ImpactPagePublic)
async def glossary_version_impact(
    version_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    change_id: Annotated[uuid.UUID | None, Query(description="Только по этому изменению")] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> ImpactPagePublic:
    """Блоки книги, которые задевают изменения версии, — что перепроверять."""
    page = await GlossaryVersionService(session, context).impact(
        version_id, change_id=change_id, limit=limit, offset=offset
    )

    return ImpactPagePublic(
        total=page.total,
        items=[
            ImpactedBlockPublic(
                block=BlockRefPublic(
                    id=item.block.id,
                    code=item.block.code,
                    full_code=(f"{item.chapter.code}-" if item.chapter.code else "")
                    + item.block.code,
                    kind=item.block.kind,
                    text=item.block.source_text,
                    active=item.block.active,
                    row=None,
                    column=None,
                ),
                chapter_id=item.chapter.id,
                chapter_code=item.chapter.code,
                terms=item.terms,
            )
            for item in page.items
        ],
    )


def gate_public(gate: Gate) -> TerminologyGatePublic:
    state = gate.state

    return TerminologyGatePublic(
        chapter_id=state.chapter.id,
        chapter_code=state.chapter.code,
        chapter_title=state.chapter.title,
        ordinal=state.chapter.ordinal,
        open=gate.open,
        version=None
        if gate.version is None
        else GlossaryVersionPublic.model_validate(gate.version),
        draft=None if gate.draft is None else GlossaryVersionPublic.model_validate(gate.draft),
        blockers=[_item(item) for item in gate.blockers],
        warnings=[_item(item) for item in gate.warnings],
        master_id=None if state.master is None else state.master.id,
        current_pass=None
        if state.current_pass is None
        else TerminologyPassPublic.model_validate(state.current_pass),
        collected=state.collected,
        undecided=state.undecided,
    )


def _item(item: GateItem) -> GateItemPublic:
    return GateItemPublic(
        code=item.code, message=item.message, chapter_id=item.chapter_id, count=item.count
    )
