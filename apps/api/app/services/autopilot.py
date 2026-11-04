"""Автоматический режим: сервис ведёт книгу по тому же конвейеру, что и человек.

Обходных путей здесь нет: зовутся те же сервисы, с теми же проверками и теми же записями. Поэтому
у выпуска тот же манифест и та же воспроизводимость, что у собранного вручную. Разница в одном:
решение принимает сервис, и каждое такое решение пишется в журнал как автоматическое.

Заход короткий и повторяемый: сервис смотрит, в каком состоянии книга на самом деле, и делает
следующий шаг. Долгое (перевод, проверки, сборка файлов) ставится обычным заданием в очередь,
следующий заход увидит результат. Падение рабочего поэтому ничего не ломает.

Сервис не решает за человека то, в чём не уверен. Незакрытое критичное или серьёзное замечание,
неразборчивая надпись, превышение сметы и любой отказ останавливают прогон, и экран показывает, что
именно ждёт решения. Закрывать замечания сервис не умеет намеренно: иначе «без заморочек» значило бы
«молча выпустили с ошибкой».
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.autopilot import AutopilotRun, AutopilotStatus
from app.models.book import BookEdition, SourceValidationResult
from app.models.chapter import BoundaryStatus, Chapter
from app.models.document import Document
from app.models.figure import FigureStatus
from app.models.issue import Issue, IssueSeverity
from app.models.job import LIVE, JobState, TranslationJob
from app.models.master import ChapterMaster
from app.models.organization import Role
from app.models.qa import QAKind
from app.models.release import ArtifactFormat, BookRelease, BookReleaseStatus, PageStatus
from app.models.review import ReviewKind, ReviewRun, ReviewStatus
from app.models.terminology import TermCandidateStatus
from app.services.artifacts import ArtifactService
from app.services.assembly import BLOCKER, AssemblyService
from app.services.audit import AuditService
from app.services.base import TenantService
from app.services.chapter_approval import ChapterApprovalService
from app.services.chapter_detection import ChapterDetectionService
from app.services.chapter_releases import ChapterReleaseService
from app.services.context import RequestContext
from app.services.errors import ConflictError, DomainError, NotFoundError
from app.services.export.base import ExportError
from app.services.export.pdf import STUB_RENDERER, page_is_blank
from app.services.figures import FigureService
from app.services.glossary_versions import GlossaryVersionService
from app.services.issue_status import OPEN
from app.services.masters import MasterService
from app.services.profiling import EstimateService
from app.services.providers import provider_name
from app.services.providers.base import ProviderError, TranslationProvider, TranslationRequest
from app.services.qa import QAService
from app.services.release_gate import ReleaseGateService
from app.services.reviews import ReviewService
from app.services.source_validation import SourceValidationService
from app.services.storage import ObjectStorage
from app.services.terminology import Decision, TerminologyService
from app.services.terminology_gate import TerminologyGate
from app.services.translation_runs import ChapterTranslationService
from app.services.workspace import WorkspaceSettingsService

RUNNING_ROLES = (Role.ADMIN, Role.MANAGER)

LEASE = timedelta(minutes=10)

# Сколько раз пробуем один и тот же шаг. Дальше — к человеку: повторять без конца значит платить.
MAX_ATTEMPTS = 2

TERM_MIN_FREQUENCY_DEFAULT = 5
EMPTY_GLOSSARY_REASON = "Автоматический режим: терминов выше порога в книге не нашлось"

STAGES = (
    ("structure", "Главы книги"),
    ("masters", "Тексты глав"),
    ("terms", "Термины"),
    ("translation", "Перевод"),
    ("checks", "Проверки"),
    ("figures", "Рисунки"),
    ("reviews", "Сверка"),
    ("chapters", "Финальные версии глав"),
    ("release", "Сборка книги"),
    ("files", "Файлы DOCX и PDF"),
    ("audit", "Страницы PDF"),
    ("done", "Готово"),
)


class WaitingForQueueError(Exception):
    """Идёт задание в очереди: следующий заход увидит результат."""


class RunStoppedError(Exception):
    """Прогон остановили, пока шёл заход: дальше решать нельзя."""


class NeedsHumanError(Exception):
    def __init__(self, reasons: list[dict[str, Any]]) -> None:
        super().__init__("Нужно решение человека")
        self.reasons = reasons


def _reason(
    code: str,
    message: str,
    *,
    chapter_id: uuid.UUID | None = None,
    issue_id: uuid.UUID | None = None,
    figures: bool = False,
    release_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "chapter_id": str(chapter_id) if chapter_id is not None else None,
        "issue_id": str(issue_id) if issue_id is not None else None,
        "figures": figures,
        "release_id": str(release_id) if release_id is not None else None,
    }


@dataclass(frozen=True, slots=True)
class AutopilotView:
    run: AutopilotRun
    chapters_total: int
    chapters_done: int


class AutopilotService(TenantService):
    def __init__(
        self, session: AsyncSession, context: RequestContext, storage: ObjectStorage
    ) -> None:
        super().__init__(session, context)
        self._storage = storage

    async def start(
        self,
        book_id: uuid.UUID,
        *,
        term_min_frequency: int = TERM_MIN_FREQUENCY_DEFAULT,
        semantic: bool = True,
        budget_usd: float | None = None,
    ) -> AutopilotRun:
        self._context.require(*RUNNING_ROLES)

        book = await self._book(book_id)
        live = await self._live(book.id)
        if live is not None:
            raise ConflictError("Автоматический режим по этой книге уже идёт")

        run = AutopilotRun(
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            book_id=book.id,
            status=AutopilotStatus.RUNNING,
            stage=STAGES[0][0],
            profile={
                "term_min_frequency": term_min_frequency,
                "semantic": semantic,
                "budget_usd": budget_usd,
            },
            waiting=[],
            attempts={},
            started_by_id=self._context.user.id,
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cache_write_tokens=0,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(run)
                await self._session.flush()
        except IntegrityError as error:
            raise ConflictError("Автоматический режим по этой книге уже идёт") from error

        self._audit(run, "started", dict(run.profile))
        await self._session.commit()

        return run

    async def latest(self, book_id: uuid.UUID) -> AutopilotView | None:
        book = await self._book(book_id)
        run = await self._session.scalar(
            self.scoped(AutopilotRun)
            .where(AutopilotRun.book_id == book.id)
            .order_by(AutopilotRun.created_at.desc())
            .limit(1)
        )
        if run is None:
            return None

        chapters = list(
            await self._session.scalars(self.scoped(Chapter).where(Chapter.book_id == book.id))
        )
        done = 0
        releases = ChapterReleaseService(self._session, self._context, self._storage)
        for chapter in chapters:
            rows = await releases.of_chapter(chapter.id)
            if any(row.release.status.value == "approved" for row in rows):
                done += 1

        return AutopilotView(run=run, chapters_total=len(chapters), chapters_done=done)

    async def resume(self, run_id: uuid.UUID, *, budget_usd: float | None = None) -> AutopilotRun:
        """Человек решил: продолжить. Счётчики повторов обнуляются, смета при желании новая."""
        self._context.require(*RUNNING_ROLES)

        run = await self._run(run_id)
        if run.status is not AutopilotStatus.WAITING_HUMAN:
            raise ConflictError("Прогон не ждёт решения")

        run.status = AutopilotStatus.RUNNING
        run.waiting = []
        run.attempts = {}
        run.lease_until = None
        if budget_usd is not None:
            run.profile = {**run.profile, "budget_usd": budget_usd}

        self._audit(run, "resumed", {"budget_usd": budget_usd})
        await self._session.commit()

        return run

    async def cancel(self, run_id: uuid.UUID) -> AutopilotRun:
        self._context.require(*RUNNING_ROLES)

        run = await self._run(run_id)
        if run.status not in (AutopilotStatus.RUNNING, AutopilotStatus.WAITING_HUMAN):
            raise ConflictError("Прогон уже закончен")

        run.status = AutopilotStatus.CANCELLED
        run.finished_at = datetime.now(UTC)
        run.waiting = []
        self._audit(run, "cancelled", {})
        await self._session.commit()

        return run

    async def advance(self, run_id: uuid.UUID, *, provider: TranslationProvider) -> None:
        """Один заход: дойти до ближайшего ожидания или остановки."""
        run = await self._run(run_id)

        try:
            await self._drive(run, provider)
        except WaitingForQueueError:
            pass
        except RunStoppedError:
            await self._rollback()
            return
        except NeedsHumanError as stop:
            await self._rollback()
            await self._stop(run_id, stop.reasons)
            return
        except (DomainError, ExportError, ProviderError) as error:
            # Отказ сервиса — такой же повод спросить человека: текст уже написан для него.
            await self._rollback()
            await self._stop(run_id, [_reason("refused", str(error))])
            return

        run = await self._run(run_id)
        run.lease_until = None
        await self._session.commit()

    # ── шаги ──

    async def _drive(self, run: AutopilotRun, provider: TranslationProvider) -> None:
        book = await self._book(run.book_id)

        await self._mark(run, "structure")
        chapters = await self._structure(run, book)

        await self._mark(run, "masters")
        for chapter in chapters:
            await self._master(run, chapter)

        await self._mark(run, "terms")
        for chapter in chapters:
            await self._mark(run, "terms")
            await self._terms(run, book, chapter, provider)
        await self._glossary(run, book, chapters)

        await self._budget(run, chapters)

        for chapter in chapters:
            await self._chapter(run, chapter)

        await self._mark(run, "release")
        release = await self._release(run, book)

        await self._mark(run, "files")
        await self._files(run, release)

        await self._mark(run, "audit")
        await self._audit_pages(run, release)
        await self._finish(run, release)

    async def _validate_sources(self, run: AutopilotRun, book: BookEdition) -> None:
        """Та же проверка комплекта, что кнопка на экране: негодный файл держит книгу."""
        documents = list(
            await self._session.scalars(self.scoped(Document).where(Document.book_id == book.id))
        )
        results = {
            row.document_id: row
            for row in await self._session.scalars(
                self.scoped(SourceValidationResult).where(
                    SourceValidationResult.document_id.in_([item.id for item in documents])
                )
            )
        }
        checker = SourceValidationService(self._session, self._context, self._storage)

        for document in documents:
            result = results.get(document.id)

            if result is None:
                result = await checker.validate(document.id)
                self._audit(
                    run,
                    "source_validated",
                    {"document_id": str(document.id), "format_ok": result.format_ok},
                )

            if not result.format_ok:
                raise NeedsHumanError(
                    [
                        _reason(
                            "source_invalid",
                            f"Файл «{document.original_filename or document.title}» не прошёл "
                            "проверку: замените его в комплекте книги",
                        )
                    ]
                )

    async def _structure(self, run: AutopilotRun, book: BookEdition) -> list[Chapter]:
        await self._validate_sources(run, book)

        chapters = await self._chapters(book.id)

        if not chapters:
            await ChapterDetectionService(self._session, self._context, self._storage).propose(
                book.id
            )
            chapters = await self._chapters(book.id)
            self._audit(run, "chapters_proposed", {"chapters": len(chapters)})

        if not chapters:
            raise NeedsHumanError(
                [_reason("no_chapters", "В основном источнике книги не нашлось глав")]
            )

        if any(item.boundary_status is not BoundaryStatus.APPROVED for item in chapters):
            await ChapterApprovalService(self._session, self._context).approve_all(book.id)
            self._audit(run, "boundaries_approved", {"chapters": len(chapters)})
            await self._session.commit()
            chapters = await self._chapters(book.id)

        return chapters

    async def _master(self, run: AutopilotRun, chapter: Chapter) -> None:
        masters = MasterService(self._session, self._context, self._storage)
        versions = await masters.versions(chapter.id)
        master: ChapterMaster | None = versions[0] if versions else None

        if master is None:
            master = await masters.extract(chapter.id, reason=None)
            self._audit(run, "master_extracted", {"chapter_id": str(chapter.id)})

        if master.approved_at is None:
            await masters.approve(master.id)
            self._audit(run, "master_approved", {"chapter_id": str(chapter.id)})
            await self._session.commit()

    async def _terms(
        self,
        run: AutopilotRun,
        book: BookEdition,
        chapter: Chapter,
        provider: TranslationProvider,
    ) -> None:
        """Кандидат принимается при частоте выше порога, остальные отклоняются.

        Принятый сервисом термин не обязателен: это подсказка переводу. Обязательным его делает
        человек, иначе машинное решение останавливало бы книгу ложным расхождением в падеже.
        """
        terminology = TerminologyService(self._session, self._context)
        state = (await TerminologyGate(self._session, self._context).states([chapter]))[0]

        if not state.collected:
            await terminology.extract_chapter(chapter.id)

        pending = await terminology.chapter_candidates(chapter.id, status=TermCandidateStatus.NEW)
        if not pending:
            return

        threshold = int(run.profile["term_min_frequency"])
        chosen = [item for item in pending if item.frequency >= threshold]
        targets: dict[str, str] = {}

        if chosen:
            answer = await provider.translate(
                [
                    TranslationRequest(
                        source_text=item.source_term,
                        source_language=book.source_language,
                        target_language=book.target_language,
                        key=str(item.id),
                        kind="term",
                    )
                    for item in chosen
                ]
            )
            targets = answer.items
            run.model = provider.name
            run.input_tokens += answer.usage.input_tokens
            run.output_tokens += answer.usage.output_tokens
            run.cached_input_tokens += answer.usage.cached_input_tokens
            run.cache_write_tokens += answer.usage.cache_write_tokens

        decisions = [
            Decision(
                candidate_id=item.id,
                accept=True,
                target_term=targets[str(item.id)].strip(),
                mandatory=False,
            )
            if targets.get(str(item.id), "").strip()
            else Decision(candidate_id=item.id, accept=False)
            for item in pending
        ]
        await terminology.decide_chapter(chapter.id, decisions)
        self._audit(
            run,
            "terms_decided",
            {
                "chapter_id": str(chapter.id),
                "threshold": threshold,
                "accepted": sum(1 for item in decisions if item.accept),
                "rejected": sum(1 for item in decisions if not item.accept),
            },
        )
        await self._session.commit()

    async def _glossary(
        self, run: AutopilotRun, book: BookEdition, chapters: list[Chapter]
    ) -> None:
        gate = TerminologyGate(self._session, self._context)
        checks = [await gate.check(chapter.id) for chapter in chapters]
        if all(item.open for item in checks):
            return

        versions = GlossaryVersionService(self._session, self._context)
        draft = await versions.create_draft(book.id)
        await versions.approve(
            draft.id, empty_reason=EMPTY_GLOSSARY_REASON if draft.term_count == 0 else None
        )
        self._audit(run, "glossary_approved", {"version": draft.number, "terms": draft.term_count})
        await self._session.commit()

    async def _budget(self, run: AutopilotRun, chapters: list[Chapter]) -> None:
        limit = run.profile.get("budget_usd")
        if limit is None:
            return

        estimated = 0.0
        for chapter in chapters:
            usd = await self._estimate(chapter.id)
            if usd is None:
                # Цен модели нет: предел не проверить, а молча считать это нулём нельзя.
                raise NeedsHumanError(
                    [
                        _reason(
                            "unknown_price",
                            "Смету посчитать нельзя: для этой модели нет цен. Выберите в "
                            "настройках другую модель или остановите прогон",
                        )
                    ]
                )
            estimated += usd

        if estimated > float(limit):
            raise NeedsHumanError(
                [
                    _reason(
                        "over_budget",
                        f"Смета перевода около ${estimated:.2f}, предел ${float(limit):.2f}: "
                        "поднимите предел или остановите прогон",
                    )
                ]
            )

    async def _estimate(self, chapter_id: uuid.UUID) -> float | None:
        """Смета главы в долларах: та же, что на экране главы. Пусто, если цен модели нет."""
        model = await WorkspaceSettingsService(self._session, self._context).model()
        found = await EstimateService(self._session, self._context).build(
            chapter_id,
            model=provider_name(model),
            context_segments=get_settings().translation_context_segments,
        )

        # Сметы нет только там, где платить не за что.
        return found.estimate.usd if found.estimate is not None else 0.0

    async def _chapter(self, run: AutopilotRun, chapter: Chapter) -> None:
        name = chapter.code or f"глава {chapter.ordinal}"

        await self._require_no_live_job(chapter)

        checks = QAService(self._session, self._context)
        state = await checks.state(chapter.id)

        await self._mark(run, "translation")
        if state.translated < state.total:
            self._attempt(
                run,
                f"translate:{chapter.id}",
                _reason(
                    "untranslated",
                    f"В главе {name} не переведено блоков: {state.total - state.translated}",
                    chapter_id=chapter.id,
                ),
            )
            await ChapterTranslationService(self._session, self._context).start(chapter.id)
            await self._session.commit()
            raise WaitingForQueueError

        await self._mark(run, "checks")
        if state.formal < state.translated:
            self._attempt(
                run,
                f"formal:{chapter.id}",
                _reason(
                    "formal_incomplete",
                    f"Формальная проверка главы {name} не покрыла текст",
                    chapter_id=chapter.id,
                ),
            )
            await checks.start(chapter.id, QAKind.DETERMINISTIC)
            await self._session.commit()
            raise WaitingForQueueError

        # Сверка считается сделанной, только если прошла целиком: сорвавшийся прогон и блоки,
        # которые модель не проверила, выдавать за проверенные нельзя.
        latest = state.latest_semantic
        if run.profile.get("semantic") and (
            latest is None
            or latest.run.revision_set_hash != state.revision_set_hash
            or latest.job is None
            or latest.job.state is not JobState.DONE
            or bool(latest.run.rejections)
        ):
            self._attempt(
                run,
                f"semantic:{chapter.id}",
                _reason(
                    "semantic_incomplete",
                    f"Смысловая сверка главы {name} не завершилась",
                    chapter_id=chapter.id,
                ),
            )
            await checks.start(chapter.id, QAKind.SEMANTIC)
            await self._session.commit()
            raise WaitingForQueueError

        await self._stop_on_issues(chapter)

        await self._mark(run, "figures")
        await self._figures(run, chapter)

        await self._mark(run, "reviews")
        await self._reviews(run, chapter)

        await self._mark(run, "chapters")
        await self._release_chapter(run, chapter)

    async def _stop_on_issues(self, chapter: Chapter) -> None:
        """Критичное и серьёзное решает только человек: закрывать их сервис не умеет."""
        rows = list(
            await self._session.scalars(
                self.scoped(Issue)
                .where(
                    Issue.chapter_id == chapter.id,
                    Issue.severity.in_((IssueSeverity.CRITICAL, IssueSeverity.MAJOR)),
                    Issue.status.in_(OPEN),
                    Issue.archived_at.is_(None),
                )
                .order_by(Issue.severity, Issue.code)
                .limit(50)
            )
        )
        if rows:
            raise NeedsHumanError(
                [
                    _reason(
                        "open_issue",
                        f"Замечание {row.code} ждёт решения",
                        chapter_id=chapter.id,
                        issue_id=row.id,
                    )
                    for row in rows
                ]
            )

    async def _figures(self, run: AutopilotRun, chapter: Chapter) -> None:
        figures = FigureService(self._session, self._context, self._storage)
        images = await figures.of_chapter(chapter.id)
        if not images:
            return

        if any(image.current is None for image in images):
            self._attempt(
                run,
                f"figures:{chapter.id}",
                _reason(
                    "figures_unread",
                    f"Рисунки главы {chapter.code} не прочитаны",
                    chapter_id=chapter.id,
                    figures=True,
                ),
            )
            await figures.request(chapter.id)
            raise WaitingForQueueError

        unsure: list[dict[str, Any]] = []

        for image in images:
            current = image.current
            assert current is not None

            if current.status is not FigureStatus.DRAFT:
                continue

            if current.needs_human or current.asset_key is None:
                unsure.append(
                    _reason(
                        "figure_needs_human",
                        f"Рисунок {image.code} требует решения человека"
                        + (f": {current.note}" if current.note else ""),
                        chapter_id=chapter.id,
                        figures=True,
                    )
                )
                continue

            await figures.approve_automatically(current.id)
            self._audit(
                run, "figure_approved", {"translation_id": str(current.id), "code": image.code}
            )
            await self._session.commit()

        if unsure:
            raise NeedsHumanError(unsure)

    async def _reviews(self, run: AutopilotRun, chapter: Chapter) -> None:
        """Сверка без человека. Манифест и экран честно говорят, что человек этого не видел."""
        reviews = ReviewService(self._session, self._context, self._storage)

        for kind in (ReviewKind.TECHNICAL, ReviewKind.LITERARY, ReviewKind.FINAL_COMPARE):
            found = await self._session.scalar(
                self.scoped(ReviewRun)
                .where(
                    ReviewRun.chapter_id == chapter.id,
                    ReviewRun.kind == kind,
                    ReviewRun.status == ReviewStatus.COMPLETED,
                )
                .order_by(ReviewRun.completed_at.desc())
                .limit(1)
            )
            view = await reviews.get(found.id) if found is not None else None

            # Устаревшая техническая редакция после стиля — норма, действующей обязана быть сверка.
            if view is not None and (kind is not ReviewKind.FINAL_COMPARE or not view.stale):
                continue

            await reviews.complete_automatically(chapter.id, kind)
            self._audit(
                run, "review_completed", {"chapter_id": str(chapter.id), "kind": kind.value}
            )
            await self._session.commit()
            await self._require_no_live_job(chapter)

    async def _release_chapter(self, run: AutopilotRun, chapter: Chapter) -> None:
        releases = ChapterReleaseService(self._session, self._context, self._storage)
        rows = await releases.of_chapter(chapter.id)
        latest = rows[0] if rows else None

        if (
            latest is not None
            and latest.release.status.value == "approved"
            and not latest.working_differs
        ):
            return

        if latest is None or latest.release.status.value == "approved":
            gate = await releases.gate(chapter.id)
            if not gate.ready:
                raise NeedsHumanError(
                    [
                        _reason(item.code, item.message, chapter_id=chapter.id)
                        for item in gate.blockers
                    ]
                )
            latest = await releases.create(chapter.id, automatic=True)

        await releases.approve(latest.release.id)
        self._audit(run, "chapter_released", {"code": latest.release.code})
        await self._session.commit()

    async def _release(self, run: AutopilotRun, book: BookEdition) -> BookRelease:
        assembly = AssemblyService(self._session, self._context)
        plan = await assembly.plan(book.id)
        blockers = [item for item in plan.problems if item.severity == BLOCKER]
        if blockers:
            raise NeedsHumanError(
                [_reason(item.code, item.message, chapter_id=item.chapter_id) for item in blockers]
            )

        release, created = await assembly.build(book.id, [item.id for item in plan.chosen])
        run.release_id = release.id
        if created:
            self._audit(run, "book_built", {"code": release.code})
        await self._session.commit()

        return release

    async def _files(self, run: AutopilotRun, release: BookRelease) -> None:
        if release.status is BookReleaseStatus.PASSED:
            return

        artifacts = ArtifactService(self._session, self._context, self._storage)
        files = await artifacts.files(release.id)

        if files.job is not None and files.job.state in LIVE:
            raise WaitingForQueueError

        kinds = {row.format for row in files.artifacts}
        if kinds == set(ArtifactFormat):
            return

        if files.job is not None and files.job.state is JobState.FAILED:
            raise NeedsHumanError(
                [
                    _reason(
                        "render_failed",
                        f"Файлы не собрались: {files.job.error or 'причина не записана'}",
                        release_id=release.id,
                    )
                ]
            )

        await artifacts.request_render(release.id)
        raise WaitingForQueueError

    async def _audit_pages(self, run: AutopilotRun, release: BookRelease) -> None:
        """Автоматическая проверка страниц: только «не пустая». Вёрстку глазами она не заменяет."""
        if release.status is BookReleaseStatus.PASSED:
            return

        artifacts = ArtifactService(self._session, self._context, self._storage)
        files = await artifacts.files(release.id)
        pdf = next(row for row in files.artifacts if row.format is ArtifactFormat.PDF)
        pages = await artifacts.pages(pdf.id)
        waiting = [row for row in pages if row.status is PageStatus.UNREVIEWED]
        if not waiting:
            return

        content = await artifacts.read(pdf)
        blank: list[int] = []
        now = datetime.now(UTC)

        for page in waiting:
            empty = pdf.renderer_version != STUB_RENDERER and await asyncio.to_thread(
                page_is_blank, content, page.page_no
            )
            if empty:
                blank.append(page.page_no)
                continue

            page.status = PageStatus.AUTO_PASS
            page.checked_at = now

        await self._session.commit()

        if blank:
            raise NeedsHumanError(
                [
                    _reason(
                        "blank_page",
                        f"Страница {number} файла PDF пуста: проверьте её глазами",
                        release_id=release.id,
                    )
                    for number in blank
                ]
            )

    async def _finish(self, run: AutopilotRun, release: BookRelease) -> None:
        # Подтверждение необратимо: перед ним прогон проверяется ещё раз.
        await self._mark(run, "audit")

        if release.status is not BookReleaseStatus.PASSED:
            gate = ReleaseGateService(self._session, self._context, self._storage)
            result = await gate.check(release.id)
            if not result.ready:
                raise NeedsHumanError(
                    [
                        _reason(
                            row.code,
                            row.message,
                            chapter_id=row.chapter_id,
                            issue_id=row.issue_id,
                            release_id=release.id,
                        )
                        for row in result.blockers
                    ]
                )
            await gate.pass_release(release.id, automatic=True)

        run = await self._run(run.id)
        # Прогон могли отменить, пока шло подтверждение: отмена важнее.
        if run.status is not AutopilotStatus.RUNNING:
            return

        run.status = AutopilotStatus.DONE
        run.stage = "done"
        run.finished_at = datetime.now(UTC)
        run.lease_until = None
        self._audit(run, "finished", {"release_id": str(release.id), "code": release.code})
        await self._session.commit()

    # ── общее ──

    async def _rollback(self) -> None:
        """Откат сбрасывает все загруженные объекты, а журнал читает пользователя из контекста."""
        await self._session.rollback()
        await self._session.refresh(self._context.user)

    def _attempt(self, run: AutopilotRun, key: str, reason: dict[str, Any]) -> None:
        count = int(run.attempts.get(key, 0))
        if count >= MAX_ATTEMPTS:
            raise NeedsHumanError([reason])

        run.attempts = {**run.attempts, key: count + 1}

    async def _require_no_live_job(self, chapter: Chapter) -> None:
        job = await self._session.scalar(
            self.scoped(TranslationJob)
            .where(TranslationJob.chapter_id == chapter.id, TranslationJob.state.in_(LIVE))
            .limit(1)
        )
        if job is not None:
            raise WaitingForQueueError

    async def _mark(self, run: AutopilotRun, stage: str) -> None:
        """Перед шагом: прогон могли отменить, а срок захода не должен истечь посреди него."""
        await self._session.refresh(run, attribute_names=["status"])
        if run.status is not AutopilotStatus.RUNNING:
            raise RunStoppedError

        run.stage = stage
        run.lease_until = datetime.now(UTC) + LEASE
        await self._session.commit()

    async def stop_after_failure(self, run_id: uuid.UUID) -> None:
        """Заход сорвался неожиданно. Причина в журнале, человеку остаётся понятная фраза."""
        await self._rollback()
        await self._stop(
            run_id,
            [
                _reason(
                    "failed", "Сбой при обработке книги: повторите, подробности в журнале сервера"
                )
            ],
        )

    async def _stop(self, run_id: uuid.UUID, reasons: list[dict[str, Any]]) -> None:
        run = await self._run(run_id)
        # Прогон могли отменить, пока шёл заход: отмена важнее.
        if run.status is not AutopilotStatus.RUNNING:
            return

        run.status = AutopilotStatus.WAITING_HUMAN
        run.waiting = reasons
        run.lease_until = None
        self._audit(run, "needs_human", {"reasons": [row["code"] for row in reasons]})
        await self._session.commit()

    def _audit(self, run: AutopilotRun, decision: str, details: dict[str, Any]) -> None:
        AuditService(self._session, self._context).record(
            kind=f"autopilot.{decision}",
            subject_type="autopilot_run",
            subject_id=run.id,
            payload={"automatic": True, "book_id": str(run.book_id), **details},
        )

    async def _run(self, run_id: uuid.UUID) -> AutopilotRun:
        run = await self._session.scalar(
            self.scoped(AutopilotRun)
            .where(AutopilotRun.id == run_id)
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise NotFoundError("Такого прогона нет")

        return run

    async def _live(self, book_id: uuid.UUID) -> AutopilotRun | None:
        found: AutopilotRun | None = await self._session.scalar(
            self.scoped(AutopilotRun).where(
                AutopilotRun.book_id == book_id,
                AutopilotRun.status.in_((AutopilotStatus.RUNNING, AutopilotStatus.WAITING_HUMAN)),
            )
        )

        return found

    async def _book(self, book_id: uuid.UUID) -> BookEdition:
        book = await self._session.scalar(self.scoped(BookEdition).where(BookEdition.id == book_id))
        if book is None:
            raise NotFoundError("Книга не найдена")

        return book

    async def _chapters(self, book_id: uuid.UUID) -> list[Chapter]:
        return list(
            await self._session.scalars(
                self.scoped(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.ordinal)
            )
        )


async def claim_next(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None] | None:
    """Взять прогон на один заход. Срок вместо долгой блокировки: заход зовёт много коммитов."""
    now = datetime.now(UTC)
    run = await session.scalar(
        select(AutopilotRun)
        .where(
            AutopilotRun.status == AutopilotStatus.RUNNING,
            (AutopilotRun.lease_until.is_(None)) | (AutopilotRun.lease_until < now),
        )
        .order_by(AutopilotRun.updated_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None

    run.lease_until = now + LEASE
    claimed = (run.id, run.organization_id, run.started_by_id)
    await session.commit()

    return claimed
