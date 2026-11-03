"""Перевод надписей на рисунках и задание очереди для него.

Запись неизменяема, кроме решения по черновику: правка заводит новую версию. Напрямую не удаляется,
каскад удаления организации проходит.

Revision ID: 0025_figure_translations
Revises: 0024_artifacts_and_pass
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_figure_translations"
down_revision: str | None = "0024_artifacts_and_pass"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

JOB_CHECK_OLD = (
    "(kind = 'CHAPTER' AND chapter_id IS NOT NULL AND run_id IS NOT NULL "
    "AND qa_run_id IS NULL AND book_release_id IS NULL) "
    "OR (kind = 'QA' AND chapter_id IS NOT NULL AND qa_run_id IS NOT NULL "
    "AND run_id IS NULL AND book_release_id IS NULL) "
    "OR (kind = 'RENDER' AND book_release_id IS NOT NULL AND chapter_id IS NULL "
    "AND run_id IS NULL AND qa_run_id IS NULL)"
)
JOB_CHECK = (
    JOB_CHECK_OLD + " OR (kind = 'FIGURES' AND chapter_id IS NOT NULL AND run_id IS NULL "
    "AND qa_run_id IS NULL AND book_release_id IS NULL)"
)


def _swap_job_kind(*values: str) -> None:
    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum(*values, name="job_kind").create(op.get_bind())
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")


def upgrade() -> None:
    # Ограничение снимается раньше смены типа: оно сравнивает колонку со значениями старого типа.
    op.drop_constraint("translation_job_has_one_run", "translation_jobs", type_="check")
    _swap_job_kind("CHAPTER", "QA", "RENDER", "FIGURES")
    op.create_check_constraint("translation_job_has_one_run", "translation_jobs", JOB_CHECK)

    op.create_table(
        "figure_translations",
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
            "chapter_id", UUID, sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "object_id", UUID, sa.ForeignKey("book_objects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("image_index", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "APPROVED", "KEPT_ORIGINAL", "NO_TEXT", name="figure_status"),
            nullable=False,
        ),
        sa.Column("regions", postgresql.JSONB(), nullable=False),
        sa.Column("needs_human", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("model", sa.String(120)),
        sa.Column("asset_key", sa.String(500)),
        sa.Column("asset_sha256", sa.String(64)),
        sa.Column("media_type", sa.String(80)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint(
            "object_id", "image_index", "version", name="figure_translation_version"
        ),
    )
    op.create_index("figure_translations_chapter", "figure_translations", ["chapter_id"])

    op.execute(
        """
        CREATE FUNCTION figure_translation_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF pg_trigger_depth() < 2 THEN
                    RAISE EXCEPTION 'Перевод рисунка не удаляется'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.status <> 'DRAFT' THEN
                RAISE EXCEPTION 'Решение по рисунку не меняется: заводится новая версия'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF (NEW.object_id, NEW.image_index, NEW.version, NEW.source_sha256, NEW.regions,
                NEW.asset_key, NEW.asset_sha256, NEW.media_type)
               IS DISTINCT FROM
               (OLD.object_id, OLD.image_index, OLD.version, OLD.source_sha256, OLD.regions,
                OLD.asset_key, OLD.asset_sha256, OLD.media_type) THEN
                RAISE EXCEPTION 'Версия перевода рисунка не меняется: заводится новая'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER figure_translations_guard
        BEFORE UPDATE OR DELETE ON figure_translations
        FOR EACH ROW EXECUTE FUNCTION figure_translation_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER figure_translations_guard ON figure_translations")
    op.execute("DROP FUNCTION figure_translation_guard()")
    op.drop_index("figure_translations_chapter", table_name="figure_translations")
    op.drop_table("figure_translations")
    op.execute("DROP TYPE figure_status")

    op.execute("DELETE FROM translation_jobs WHERE kind = 'FIGURES'")
    op.drop_constraint("translation_job_has_one_run", "translation_jobs", type_="check")
    _swap_job_kind("CHAPTER", "QA", "RENDER")
    op.create_check_constraint("translation_job_has_one_run", "translation_jobs", JOB_CHECK_OLD)
