"""Прогоны проверок: находки, покрытие редакций, задание нового вида.

Задание очереди теперь выполняет либо прогон перевода, либо прогон проверки, ровно один. Одно
живое задание на главу остаётся общим: пока текст проверяется, он не должен меняться, и наоборот.

Значение перечисления в Postgres не удалить, поэтому тип заменяется целиком и в обе стороны; это же
позволяет остаться в одной транзакции.

Revision ID: 0020_qa_runs
Revises: 0019_issue_registry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_qa_runs"
down_revision: str | None = "0019_issue_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

CATEGORIES = (
    "TRANSLATION",
    "TERMINOLOGY",
    "SEMANTIC",
    "NUMBER",
    "FORMULA",
    "TABLE",
    "FIGURE",
    "CODE",
    "TECHNICAL",
    "STYLE",
    "CROSS_REFERENCE",
    "SOURCE_ERROR",
    "LAYOUT",
)
KIND = postgresql.ENUM("DETERMINISTIC", "SEMANTIC", name="qa_kind", create_type=False)
SCOPE = postgresql.ENUM("RISKY", "ALL", name="qa_scope", create_type=False)

FINDINGS_OLD = (
    "number, code, book_id, chapter_id, block_id, object_id, parent_issue_id, automatic, "
    "source_snapshot, target_snapshot, discovered_revision_id, discovered_revisions, description, "
    "proposed_fix, dedupe_key"
)


def _tenant() -> sa.Column:
    return sa.Column(
        "organization_id",
        UUID,
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _cascade(target: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete="CASCADE")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def _findings_trigger(columns: str) -> None:
    op.execute("DROP TRIGGER issues_findings_immutable ON issues")
    op.execute(
        f"""
        CREATE TRIGGER issues_findings_immutable
        BEFORE UPDATE OF {columns}
        ON issues
        FOR EACH ROW EXECUTE FUNCTION issue_findings_immutable()
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    KIND.create(bind)
    SCOPE.create(bind)

    op.create_table(
        "qa_runs",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("book_id", UUID, _cascade("book_editions.id"), nullable=False),
        sa.Column("chapter_id", UUID, _cascade("chapters.id"), nullable=False),
        sa.Column("master_id", UUID, _cascade("chapter_masters.id"), nullable=False),
        sa.Column("kind", KIND, nullable=False),
        sa.Column("scope", SCOPE, nullable=False),
        sa.Column("check_profile_version", sa.String(length=40), nullable=False),
        sa.Column("revision_set_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40)),
        sa.Column("model", sa.String(length=120)),
        sa.Column("requested_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("blocks_total", sa.Integer(), nullable=False),
        sa.Column("blocks_checked", sa.Integer(), nullable=False),
        sa.Column("blocks_untranslated", sa.Integer(), nullable=False),
        sa.Column("findings_total", sa.Integer(), nullable=False),
        sa.Column("issues_created", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("rejections", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index("qa_runs_chapter", "qa_runs", ["chapter_id", "created_at"])

    op.create_table(
        "revision_checks",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("revision_id", UUID, _cascade("translation_revisions.id"), nullable=False),
        sa.Column("qa_run_id", UUID, _cascade("qa_runs.id"), nullable=False),
        sa.Column("kind", KIND, nullable=False),
        sa.Column("check_profile_version", sa.String(length=40), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "revision_id", "kind", "check_profile_version", name="revision_check_once"
        ),
    )
    op.create_index("revision_checks_revision", "revision_checks", ["revision_id"])

    op.create_table(
        "qa_findings",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("qa_run_id", UUID, _cascade("qa_runs.id"), nullable=False),
        sa.Column("chapter_id", UUID, _cascade("chapters.id"), nullable=False),
        sa.Column("block_id", UUID, _cascade("blocks.id"), nullable=False),
        sa.Column("revision_id", UUID, _cascade("translation_revisions.id"), nullable=False),
        sa.Column("kind", KIND, nullable=False),
        sa.Column("check_name", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(*CATEGORIES, name="issue_category", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "severity",
            postgresql.ENUM("CRITICAL", "MAJOR", "MINOR", name="issue_severity", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "disposition",
            sa.Enum("REGISTERED", "NOT_REQUIRED", name="qa_finding_disposition"),
            nullable=False,
        ),
        sa.Column(
            "issue_id",
            UUID,
            sa.ForeignKey("issues.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column("rule", sa.String(length=40)),
        *_timestamps(),
        sa.CheckConstraint(
            "(disposition = 'REGISTERED' AND issue_id IS NOT NULL AND rule IS NULL) "
            "OR (disposition = 'NOT_REQUIRED' AND issue_id IS NULL AND rule IS NOT NULL)",
            name="qa_finding_is_resolved",
        ),
    )
    op.create_index("qa_findings_run", "qa_findings", ["qa_run_id"])
    op.create_index("qa_findings_chapter", "qa_findings", ["chapter_id", "check_name"])

    op.add_column(
        "issues",
        sa.Column(
            "qa_run_id", UUID, sa.ForeignKey("qa_runs.id", deferrable=True, initially="DEFERRED")
        ),
    )
    _findings_trigger(FINDINGS_OLD + ", qa_run_id")

    op.add_column(
        "workspace_settings",
        sa.Column("semantic_scope", SCOPE, nullable=False, server_default="RISKY"),
    )
    op.alter_column("workspace_settings", "semantic_scope", server_default=None)

    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum("CHAPTER", "QA", name="job_kind").create(bind)
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")

    op.alter_column("translation_jobs", "run_id", nullable=True)
    op.add_column(
        "translation_jobs",
        sa.Column("qa_run_id", UUID, sa.ForeignKey("qa_runs.id", ondelete="CASCADE"), unique=True),
    )
    op.create_check_constraint(
        "translation_job_has_one_run",
        "translation_jobs",
        "(kind = 'CHAPTER' AND run_id IS NOT NULL AND qa_run_id IS NULL) "
        "OR (kind = 'QA' AND qa_run_id IS NOT NULL AND run_id IS NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.execute("DELETE FROM translation_jobs WHERE kind = 'QA'")
    op.drop_constraint("translation_job_has_one_run", "translation_jobs", type_="check")
    op.drop_column("translation_jobs", "qa_run_id")
    op.alter_column("translation_jobs", "run_id", nullable=False)

    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum("CHAPTER", name="job_kind").create(bind)
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")

    op.drop_column("workspace_settings", "semantic_scope")

    _findings_trigger(FINDINGS_OLD)
    op.drop_column("issues", "qa_run_id")

    op.drop_table("qa_findings")
    op.drop_table("revision_checks")
    op.drop_table("qa_runs")

    for name in ("qa_finding_disposition", "qa_scope", "qa_kind"):
        sa.Enum(name=name).drop(bind)
