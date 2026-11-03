"""Редактура и финальная сверка: прогоны, покрытие, причина литературной правки.

Причина правки и ссылка на замечание входят в неизменяемую часть редакции: триггер пересоздаётся с
новым списком колонок.

Revision ID: 0022_review_runs
Revises: 0021_fixes_and_regression
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_review_runs"
down_revision: str | None = "0021_fixes_and_regression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

GUARDED_OLD = "block_id, revision_no, stage, origin, text, run_id, supersedes_id"


def _tenant() -> sa.Column:
    return sa.Column(
        "organization_id",
        UUID,
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def _revision_trigger(columns: str) -> None:
    op.execute("DROP TRIGGER translation_revisions_immutable ON translation_revisions")
    op.execute(
        f"""
        CREATE TRIGGER translation_revisions_immutable
        BEFORE UPDATE OF {columns}
        ON translation_revisions
        FOR EACH ROW EXECUTE FUNCTION translation_revision_immutable()
        """
    )


def upgrade() -> None:
    op.create_table(
        "review_runs",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "book_id", UUID, sa.ForeignKey("book_editions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "chapter_id", UUID, sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "kind",
            sa.Enum("TECHNICAL", "LITERARY", "FINAL_COMPARE", name="review_kind"),
            nullable=False,
        ),
        sa.Column("status", sa.Enum("OPEN", "COMPLETED", name="review_status"), nullable=False),
        sa.Column("reviewer_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("base_revision_set_hash", sa.String(length=64), nullable=False),
        sa.Column("completed_revision_set_hash", sa.String(length=64)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index(
        "review_runs_open",
        "review_runs",
        ["chapter_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.create_index("review_runs_chapter", "review_runs", ["chapter_id", "kind", "created_at"])

    op.create_table(
        "review_coverage",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("block_id", UUID, sa.ForeignKey("blocks.id", ondelete="CASCADE")),
        sa.Column(
            "revision_id", UUID, sa.ForeignKey("translation_revisions.id", ondelete="CASCADE")
        ),
        sa.Column("object_id", UUID, sa.ForeignKey("book_objects.id", ondelete="CASCADE")),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("result", sa.Enum("OK", "ISSUE", name="review_result"), nullable=False),
        sa.Column("reviewer_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "(block_id IS NOT NULL AND revision_id IS NOT NULL AND object_id IS NULL "
            "AND content_hash IS NULL) "
            "OR (object_id IS NOT NULL AND content_hash IS NOT NULL AND block_id IS NULL "
            "AND revision_id IS NULL)",
            name="review_coverage_subject",
        ),
    )
    op.create_index("review_coverage_run", "review_coverage", ["run_id"])
    op.create_index(
        "review_coverage_block_once",
        "review_coverage",
        ["run_id", "block_id", "revision_id"],
        unique=True,
        postgresql_where=sa.text("block_id IS NOT NULL"),
    )
    op.create_index(
        "review_coverage_object_once",
        "review_coverage",
        ["run_id", "object_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("object_id IS NOT NULL"),
    )

    reason = sa.Enum("STYLE", "CALQUE", "READABILITY", name="edit_reason")
    reason.create(op.get_bind())
    op.add_column("translation_revisions", sa.Column("edit_reason", reason))
    op.add_column(
        "translation_revisions",
        sa.Column(
            "issue_id", UUID, sa.ForeignKey("issues.id", deferrable=True, initially="DEFERRED")
        ),
    )
    _revision_trigger(GUARDED_OLD + ", edit_reason, issue_id")


def downgrade() -> None:
    bind = op.get_bind()

    _revision_trigger(GUARDED_OLD)
    op.drop_column("translation_revisions", "issue_id")
    op.drop_column("translation_revisions", "edit_reason")
    op.drop_table("review_coverage")
    op.drop_table("review_runs")

    for name in ("edit_reason", "review_result", "review_status", "review_kind"):
        sa.Enum(name=name).drop(bind)
