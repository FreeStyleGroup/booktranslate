"""Регрессия после исправлений и готовность памяти переводов.

В память теперь попадает только проверенное, и подсказкой служит только оно. Прежние пары человека
считаются проверенными: их и так поправил редактор. Машинные остаются в таблице, но текст из них в
перевод больше не идёт.

Revision ID: 0021_fixes_and_regression
Revises: 0020_qa_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_fixes_and_regression"
down_revision: str | None = "0020_qa_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


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


def upgrade() -> None:
    op.create_table(
        "regression_runs",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("issue_id", UUID, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "fix_revision_id",
            UUID,
            sa.ForeignKey("translation_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("OPEN", "COMPLETED", "SUPERSEDED", name="regression_status"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint("issue_id", "fix_revision_id", name="regression_run_once"),
    )
    op.create_index("regression_runs_issue", "regression_runs", ["issue_id", "created_at"])

    op.create_table(
        "regression_items",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("regression_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "SAME_SOURCE_REPEAT",
                "TERM_USAGE",
                "OBJECT_REFERENCE",
                "CROSS_REFERENCE",
                "ADJACENT_CONTEXT",
                "TABLE_CAPTION",
                "FIGURE_CAPTION",
                name="dependency_kind",
            ),
            nullable=False,
        ),
        sa.Column("block_id", UUID, sa.ForeignKey("blocks.id", ondelete="CASCADE")),
        sa.Column("object_id", UUID, sa.ForeignKey("book_objects.id", ondelete="CASCADE")),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column(
            "base_revision_id", UUID, sa.ForeignKey("translation_revisions.id", ondelete="CASCADE")
        ),
        sa.Column("proposed_text", sa.Text()),
        sa.Column("safe", sa.Boolean(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "PENDING",
                "NOT_AFFECTED",
                "PROPAGATED",
                "ISSUE_CREATED",
                name="regression_decision",
            ),
            nullable=False,
        ),
        sa.Column("decided_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text()),
        sa.Column(
            "applied_revision_id",
            UUID,
            sa.ForeignKey("translation_revisions.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column(
            "child_issue_id",
            UUID,
            sa.ForeignKey("issues.id", deferrable=True, initially="DEFERRED"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "block_id IS NOT NULL OR object_id IS NOT NULL", name="regression_item_has_subject"
        ),
    )
    op.create_index("regression_items_run", "regression_items", ["run_id"])

    publish = sa.Enum("VERIFIED", "CLOSED", name="memory_publish")
    publish.create(op.get_bind())
    op.add_column(
        "workspace_settings",
        sa.Column("memory_publish_on", publish, nullable=False, server_default="VERIFIED"),
    )
    op.alter_column("workspace_settings", "memory_publish_on", server_default=None)

    op.add_column(
        "translation_units",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE translation_units SET verified = TRUE WHERE origin = 'human'")
    op.alter_column("translation_units", "verified", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_column("translation_units", "verified")
    op.drop_column("workspace_settings", "memory_publish_on")
    op.drop_table("regression_items")
    op.drop_table("regression_runs")

    for name in ("memory_publish", "regression_decision", "dependency_kind", "regression_status"):
        sa.Enum(name=name).drop(bind)
