"""Файлы выпуска, постраничный аудит и PASS.

Задание очереди теперь выполняет ещё и сборку файлов выпуска: у такого задания нет главы, есть
выпуск. Живое задание на выпуск одно. PASS — отдельная неизменяемая запись; после него база не
даёт менять выпуск, его файлы и аудит.

Revision ID: 0024_artifacts_and_pass
Revises: 0023_releases
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_artifacts_and_pass"
down_revision: str | None = "0023_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

GUARD = """
    CREATE OR REPLACE FUNCTION book_release_guard() RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'Выпуск книги % не удаляется', OLD.code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN OLD;
        END IF;

        IF OLD.status = 'PASSED' THEN
            RAISE EXCEPTION 'Выпуск % прошёл контроль и неизменяем', OLD.code
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;

        IF (NEW.manifest, NEW.manifest_hash, NEW.version_major, NEW.version_minor, NEW.code,
            NEW.book_id)
           IS DISTINCT FROM
           (OLD.manifest, OLD.manifest_hash, OLD.version_major, OLD.version_minor, OLD.code,
            OLD.book_id) THEN
            RAISE EXCEPTION 'Состав выпуска % не меняется', OLD.code
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        {pass_check}
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
"""
PASS_CHECK = """
        IF NEW.status = 'PASSED' AND NOT EXISTS (
            SELECT 1 FROM release_passes WHERE release_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'Выпуск % нельзя отметить пройденным без записи контроля', OLD.code
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
"""


def _tenant() -> sa.Column:
    return sa.Column(
        "organization_id",
        UUID,
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _times() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # Ограничение снимается раньше смены типа: оно сравнивает колонку со значениями старого типа.
    op.drop_constraint("translation_job_has_one_run", "translation_jobs", type_="check")

    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum("CHAPTER", "QA", "RENDER", name="job_kind").create(bind)
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")

    op.add_column(
        "translation_jobs",
        sa.Column("book_release_id", UUID, sa.ForeignKey("book_releases.id", ondelete="CASCADE")),
    )
    op.alter_column("translation_jobs", "chapter_id", nullable=True)
    op.create_check_constraint(
        "translation_job_has_one_run",
        "translation_jobs",
        "(kind = 'CHAPTER' AND chapter_id IS NOT NULL AND run_id IS NOT NULL "
        "AND qa_run_id IS NULL AND book_release_id IS NULL) "
        "OR (kind = 'QA' AND chapter_id IS NOT NULL AND qa_run_id IS NOT NULL "
        "AND run_id IS NULL AND book_release_id IS NULL) "
        "OR (kind = 'RENDER' AND book_release_id IS NOT NULL AND chapter_id IS NULL "
        "AND run_id IS NULL AND qa_run_id IS NULL)",
    )
    op.create_index(
        "translation_jobs_live_release",
        "translation_jobs",
        ["book_release_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('WAITING', 'RUNNING')"),
    )

    op.add_column(
        "workspace_settings",
        sa.Column("minor_blocks_release", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("workspace_settings", "minor_blocks_release", server_default=None)

    op.create_table(
        "export_artifacts",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "release_id",
            UUID,
            sa.ForeignKey("book_releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.Enum("DOCX", "PDF", name="artifact_format"), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("renderer_version", sa.String(80), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("page_map", postgresql.JSONB()),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        *_times(),
    )
    op.create_index(
        "export_artifact_current",
        "export_artifacts",
        ["release_id", "format"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "page_audits",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "artifact_id",
            UUID,
            sa.ForeignKey("export_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("UNREVIEWED", "PASS", "ISSUE", "STALE", name="page_status"),
            nullable=False,
        ),
        sa.Column("reviewer_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "issue_id", UUID, sa.ForeignKey("issues.id", deferrable=True, initially="DEFERRED")
        ),
        *_times(),
        sa.UniqueConstraint("artifact_id", "page_no", name="page_audit_once"),
    )

    op.create_table(
        "release_passes",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "release_id",
            UUID,
            sa.ForeignKey("book_releases.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("actor_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("gate_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False),
        *_times(),
    )

    op.execute(GUARD.format(pass_check=PASS_CHECK))

    op.execute(
        """
        CREATE FUNCTION export_artifact_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF pg_trigger_depth() < 2 THEN
                    RAISE EXCEPTION 'Файл выпуска не удаляется'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN OLD;
            END IF;

            IF EXISTS (SELECT 1 FROM release_passes WHERE release_id = OLD.release_id) THEN
                RAISE EXCEPTION 'Выпуск прошёл контроль: его файлы неизменяемы'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF (NEW.release_id, NEW.format, NEW.storage_key, NEW.checksum, NEW.size,
                NEW.renderer_version, NEW.manifest_hash, NEW.page_count, NEW.page_map)
               IS DISTINCT FROM
               (OLD.release_id, OLD.format, OLD.storage_key, OLD.checksum, OLD.size,
                OLD.renderer_version, OLD.manifest_hash, OLD.page_count, OLD.page_map) THEN
                RAISE EXCEPTION 'Файл выпуска не меняется: собирается новый'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER export_artifacts_guard
        BEFORE UPDATE OR DELETE ON export_artifacts
        FOR EACH ROW EXECUTE FUNCTION export_artifact_guard()
        """
    )
    op.execute(
        """
        CREATE FUNCTION page_audit_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() >= 2 THEN
                RETURN OLD;
            END IF;

            IF TG_OP = 'DELETE' OR EXISTS (
                SELECT 1 FROM release_passes rp
                JOIN export_artifacts a ON a.release_id = rp.release_id
                WHERE a.id = OLD.artifact_id
            ) THEN
                RAISE EXCEPTION 'Аудит страницы этого выпуска не меняется'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER page_audits_guard
        BEFORE UPDATE OR DELETE ON page_audits
        FOR EACH ROW EXECUTE FUNCTION page_audit_guard()
        """
    )
    op.execute(
        """
        CREATE FUNCTION release_pass_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() >= 2 THEN
                RETURN OLD;
            END IF;

            RAISE EXCEPTION 'Запись о контроле выпуска неизменяема'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER release_passes_guard
        BEFORE UPDATE OR DELETE ON release_passes
        FOR EACH ROW EXECUTE FUNCTION release_pass_guard()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.execute("DROP TRIGGER release_passes_guard ON release_passes")
    op.execute("DROP FUNCTION release_pass_guard()")
    op.execute("DROP TRIGGER page_audits_guard ON page_audits")
    op.execute("DROP FUNCTION page_audit_guard()")
    op.execute("DROP TRIGGER export_artifacts_guard ON export_artifacts")
    op.execute("DROP FUNCTION export_artifact_guard()")
    op.execute(GUARD.format(pass_check=""))

    # Пройденные выпуски теряют запись контроля: без неё статус не имеет основания. Триггер
    # снимается на время, потому что пройденный выпуск он менять не даёт.
    op.execute("ALTER TABLE book_releases DISABLE TRIGGER book_releases_guard")
    op.execute("UPDATE book_releases SET status = 'BUILT' WHERE status = 'PASSED'")
    op.execute("ALTER TABLE book_releases ENABLE TRIGGER book_releases_guard")

    op.drop_table("release_passes")
    op.drop_table("page_audits")
    op.drop_index("export_artifact_current", table_name="export_artifacts")
    op.drop_table("export_artifacts")
    op.execute("DROP TYPE page_status")
    op.execute("DROP TYPE artifact_format")
    op.drop_column("workspace_settings", "minor_blocks_release")

    op.execute("DELETE FROM translation_jobs WHERE kind = 'RENDER'")
    op.drop_index("translation_jobs_live_release", table_name="translation_jobs")
    op.drop_constraint("translation_job_has_one_run", "translation_jobs", type_="check")
    op.alter_column("translation_jobs", "chapter_id", nullable=False)
    op.drop_column("translation_jobs", "book_release_id")

    op.execute("ALTER TYPE job_kind RENAME TO job_kind_old")
    sa.Enum("CHAPTER", "QA", name="job_kind").create(bind)
    op.execute(
        "ALTER TABLE translation_jobs ALTER COLUMN kind TYPE job_kind USING kind::text::job_kind"
    )
    op.execute("DROP TYPE job_kind_old")
    op.create_check_constraint(
        "translation_job_has_one_run",
        "translation_jobs",
        "(kind = 'CHAPTER' AND run_id IS NOT NULL AND qa_run_id IS NULL) "
        "OR (kind = 'QA' AND qa_run_id IS NOT NULL AND run_id IS NULL)",
    )
