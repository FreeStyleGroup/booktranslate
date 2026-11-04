"""Автоматический режим: прогон книги, работы без человека, автоматическая проверка страниц.

Revision ID: 0026_autopilot
Revises: 0025_figure_translations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_autopilot"
down_revision: str | None = "0025_figure_translations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


def _swap_page_status(*values: str) -> None:
    op.execute("ALTER TYPE page_status RENAME TO page_status_old")
    sa.Enum(*values, name="page_status").create(op.get_bind())
    op.execute(
        "ALTER TABLE page_audits ALTER COLUMN status TYPE page_status "
        "USING status::text::page_status"
    )
    op.execute("DROP TYPE page_status_old")


# Каскады базы проходят мимо охраны записей: удаление пользователя лишь обнуляет ссылку на него,
# и запрещать это значило бы не дать удалить человека. Запись снаружи охрана останавливает.
GUARDS = (
    ("chapter_releases_guard", "chapter_releases", "chapter_release_guard"),
    ("book_releases_guard", "book_releases", "book_release_guard"),
    ("book_release_chapters_guard", "book_release_chapters", "book_release_chapter_guard"),
    ("export_artifacts_guard", "export_artifacts", "export_artifact_guard"),
    ("page_audits_guard", "page_audits", "page_audit_guard"),
    ("release_passes_guard", "release_passes", "release_pass_guard"),
    ("figure_translations_guard", "figure_translations", "figure_translation_guard"),
)


def _recreate_guards(condition: str) -> None:
    for trigger, table, function in GUARDS:
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW {condition} EXECUTE FUNCTION {function}()
            """
        )


def upgrade() -> None:
    _recreate_guards("WHEN (pg_trigger_depth() = 0)")

    # Статус книги раньше не менялся вовсе: приводим его к тому, что с книгой уже случилось.
    op.execute(
        """
        UPDATE book_editions SET status = 'IN_PROGRESS'
        WHERE status = 'DRAFT' AND EXISTS (
            SELECT 1 FROM chapters
            WHERE chapters.book_id = book_editions.id AND chapters.boundary_status = 'APPROVED'
        )
        """
    )
    op.execute(
        """
        UPDATE book_editions SET status = 'RELEASED'
        WHERE EXISTS (
            SELECT 1 FROM book_releases
            WHERE book_releases.book_id = book_editions.id AND book_releases.status = 'PASSED'
        )
        """
    )

    op.create_table(
        "autopilot_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "book_id", UUID, sa.ForeignKey("book_editions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("RUNNING", "WAITING_HUMAN", "DONE", "CANCELLED", name="autopilot_status"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("waiting", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", postgresql.JSONB(), nullable=False),
        sa.Column("release_id", UUID, sa.ForeignKey("book_releases.id", ondelete="SET NULL")),
        sa.Column("started_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("model", sa.String(120)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index(
        "autopilot_runs_live_book",
        "autopilot_runs",
        ["book_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('RUNNING', 'WAITING_HUMAN')"),
    )
    op.create_index("autopilot_runs_queue", "autopilot_runs", ["status", "lease_until"])

    op.add_column(
        "review_runs",
        sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("review_runs", "automatic", server_default=None)

    _swap_page_status("UNREVIEWED", "PASS", "AUTO_PASS", "ISSUE", "STALE")


def downgrade() -> None:
    # Отметка «проверено автоматически» при откате не становится отметкой человека.
    op.execute("ALTER TABLE page_audits DISABLE TRIGGER page_audits_guard")
    op.execute("UPDATE page_audits SET status = 'UNREVIEWED' WHERE status = 'AUTO_PASS'")
    op.execute("ALTER TABLE page_audits ENABLE TRIGGER page_audits_guard")
    _swap_page_status("UNREVIEWED", "PASS", "ISSUE", "STALE")

    op.drop_column("review_runs", "automatic")
    op.drop_index("autopilot_runs_queue", table_name="autopilot_runs")
    op.drop_index("autopilot_runs_live_book", table_name="autopilot_runs")
    op.drop_table("autopilot_runs")
    op.execute("DROP TYPE autopilot_status")

    _recreate_guards("")
