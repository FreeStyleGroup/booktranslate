"""Перевод главы: готовность, запуск, перевод заново, история редакций.

Прогоны идут в очереди, поэтому запуск отвечает заданием, а не переводом: глава
переводится часами, а за ходом работы следят по этому же адресу.

Ручки «поправить текст редакции» здесь нет намеренно: редакция неизменяема, и
правка — это новая редакция с основанием.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContextDep, SessionDep
from app.models.block import Block
from app.schemas.chapter_translation import (
    BlockHistoryPublic,
    ChangePublic,
    ChapterBlockPage,
    ChapterBlockPublic,
    ReadinessPublic,
    RejectionPublic,
    RetranslateRequest,
    RevisionBrief,
    RevisionPublic,
    TranslationRunPublic,
    TranslationStart,
)
from app.schemas.glossary_version import GateItemPublic
from app.services.terminology_gate import GateItem
from app.services.translation_runner import is_protected
from app.services.translation_runs import (
    BlockRow,
    ChapterTranslationService,
    Readiness,
    RetranslateItem,
    RevisionView,
    RunView,
)

router = APIRouter(tags=["translation"])

MAX_PAGE = 200


@router.get("/chapters/{chapter_id}/translation", response_model=ReadinessPublic)
async def chapter_translation(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> ReadinessPublic:
    """Готова ли глава к переводу, сколько сделано и что сейчас идёт."""
    return _readiness(await ChapterTranslationService(session, context).readiness(chapter_id))


@router.post(
    "/chapters/{chapter_id}/translation",
    response_model=TranslationRunPublic,
    status_code=status.HTTP_201_CREATED,
)
async def start_translation(
    chapter_id: uuid.UUID, body: TranslationStart, context: ContextDep, session: SessionDep
) -> TranslationRunPublic:
    """Поставить в очередь перевод всего, что в главе ещё не переведено."""
    view = await ChapterTranslationService(session, context).start(
        chapter_id, ignore_terminology=body.ignore_terminology, reason=body.reason
    )

    return _run(view)


@router.post(
    "/chapters/{chapter_id}/translation/retranslate",
    response_model=TranslationRunPublic,
    status_code=status.HTTP_201_CREATED,
)
async def retranslate(
    chapter_id: uuid.UUID, body: RetranslateRequest, context: ContextDep, session: SessionDep
) -> TranslationRunPublic:
    """Получить вариант выбранных блоков. Текущие редакции остаются текущими."""
    view = await ChapterTranslationService(session, context).retranslate(
        chapter_id,
        [RetranslateItem(item.block_id, item.base_revision_id) for item in body.items],
        ignore_terminology=body.ignore_terminology,
        reason=body.reason,
    )

    return _run(view)


@router.get("/chapters/{chapter_id}/translation/runs", response_model=list[TranslationRunPublic])
async def chapter_runs(
    chapter_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> list[TranslationRunPublic]:
    """Прогоны главы, новые первыми."""
    views = await ChapterTranslationService(session, context).runs(chapter_id)

    return [_run(view) for view in views]


@router.get("/chapters/{chapter_id}/translation/blocks", response_model=ChapterBlockPage)
async def chapter_blocks(
    chapter_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChapterBlockPage:
    """Текущие блоки главы рядом с их текущими редакциями."""
    page = await ChapterTranslationService(session, context).blocks(
        chapter_id, limit=limit, offset=offset
    )

    return ChapterBlockPage(total=page.total, items=[_block(row) for row in page.items])


@router.get("/blocks/{block_id}/revisions", response_model=BlockHistoryPublic)
async def block_revisions(
    block_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BlockHistoryPublic:
    """История редакций блока: новые первыми, с происхождением и сравнением."""
    return _history(*await ChapterTranslationService(session, context).history(block_id))


@router.post("/revisions/{revision_id}/adopt", response_model=BlockHistoryPublic)
async def adopt_revision(
    revision_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> BlockHistoryPublic:
    """Принять вариант: сделать редакцию текущей. Прежняя остаётся в истории."""
    service = ChapterTranslationService(session, context)
    adopted = await service.adopt(revision_id)

    return _history(*await service.history(adopted.id))


def _history(block: Block, views: list[RevisionView]) -> BlockHistoryPublic:
    return BlockHistoryPublic(
        block_id=block.id,
        code=block.code,
        source_text=block.source_text,
        active=block.active,
        protected=is_protected(block.kind, block.source_text),
        items=[_revision(view) for view in views],
    )


def _readiness(found: Readiness) -> ReadinessPublic:
    version = found.gate.version

    return ReadinessPublic(
        chapter_id=found.chapter.id,
        open=found.open,
        bypassable=found.bypassable,
        blockers=[_item(item) for item in found.blockers],
        warnings=[_item(item) for item in found.gate.warnings],
        glossary_version_id=version.id if version is not None else None,
        glossary_label=version.label if version is not None else None,
        master_id=found.master.id if found.master is not None else None,
        master_label=found.master.label if found.master is not None else None,
        total=found.total,
        translated=found.translated,
        pending=found.pending,
        live=_run(found.live) if found.live is not None else None,
        latest=_run(found.latest) if found.latest is not None else None,
    )


def _item(item: GateItem) -> GateItemPublic:
    return GateItemPublic(
        code=item.code, message=item.message, chapter_id=item.chapter_id, count=item.count
    )


def _run(view: RunView) -> TranslationRunPublic:
    run, job = view.run, view.job

    return TranslationRunPublic(
        id=run.id,
        chapter_id=run.chapter_id,
        master_id=run.master_id,
        kind=run.kind,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        glossary_version_id=run.glossary_version_id,
        glossary_label=view.glossary_label,
        ignore_terminology=run.ignore_terminology,
        bypass_reason=run.bypass_reason,
        requested_by_id=run.requested_by_id,
        job_id=job.id if job is not None else None,
        state=job.state if job is not None else None,
        error=job.error if job is not None else None,
        blocks_total=run.blocks_total,
        blocks_done=run.from_model + run.from_memory + run.copied + len(run.rejections),
        from_model=run.from_model,
        from_memory=run.from_memory,
        copied=run.copied,
        rejections=[RejectionPublic.model_validate(item) for item in run.rejections],
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cached_input_tokens=run.cached_input_tokens,
        cache_write_tokens=run.cache_write_tokens,
        started_at=job.started_at if job is not None else None,
        finished_at=job.finished_at if job is not None else None,
        created_at=run.created_at,
    )


def _block(row: BlockRow) -> ChapterBlockPublic:
    block = row.block

    return ChapterBlockPublic(
        id=block.id,
        code=block.code,
        ordinal=block.ordinal,
        kind=block.kind,
        source_text=block.source_text,
        protected=is_protected(block.kind, block.source_text),
        current=RevisionBrief.model_validate(row.current) if row.current is not None else None,
        variants=row.variants,
    )


def _revision(view: RevisionView) -> RevisionPublic:
    revision, run = view.revision, view.run

    return RevisionPublic(
        id=revision.id,
        block_id=revision.block_id,
        revision_no=revision.revision_no,
        stage=revision.stage,
        origin=revision.origin,
        text=revision.text,
        current=view.current,
        supersedes_id=revision.supersedes_id,
        copied_from_id=revision.copied_from_id,
        memory_unit_id=revision.memory_unit_id,
        run_id=revision.run_id,
        run_kind=run.kind if run is not None else None,
        model=run.model if run is not None else None,
        prompt_version=run.prompt_version if run is not None else None,
        glossary_version_id=run.glossary_version_id if run is not None else None,
        glossary_label=view.glossary_label,
        ignore_terminology=run.ignore_terminology if run is not None else False,
        author=view.author,
        compared_with=view.compared_with,
        changes=[ChangePublic(op=item.op, text=item.text) for item in view.changes],
        created_at=revision.created_at,
    )
