"""Выпуски: финальные версии глав и сборки книги.

Неизменяемость держит база. Сумма манифеста и состав не меняются никогда, утверждённая версия
главы и пройденный выпуск книги не меняются совсем и напрямую не удаляются. Каскад удаления
организации проходит: триггер видит его по глубине вызова, как в реестре ошибок.

Revision ID: 0023_releases
Revises: 0022_review_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_releases"
down_revision: str | None = "0022_review_runs"
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


def _times() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    ]


def _deferred(target: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, deferrable=True, initially="DEFERRED")


def upgrade() -> None:
    op.create_table(
        "chapter_releases",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("book_id", UUID, _deferred("book_editions.id"), nullable=False),
        sa.Column("chapter_id", UUID, _deferred("chapters.id"), nullable=False),
        sa.Column("version_major", sa.Integer(), nullable=False),
        sa.Column("version_minor", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("status", sa.Enum("DRAFT", "APPROVED", name="release_status"), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("revision_set_hash", sa.String(64), nullable=False),
        sa.Column("master_id", UUID, _deferred("chapter_masters.id"), nullable=False),
        sa.Column("glossary_version_id", UUID, _deferred("glossary_versions.id")),
        sa.Column("technical_review_id", UUID, _deferred("review_runs.id"), nullable=False),
        sa.Column("literary_review_id", UUID, _deferred("review_runs.id"), nullable=False),
        sa.Column("final_compare_id", UUID, _deferred("review_runs.id"), nullable=False),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        *_times(),
        sa.UniqueConstraint(
            "chapter_id", "version_major", "version_minor", name="chapter_release_version"
        ),
        sa.CheckConstraint(
            "status <> 'APPROVED' OR (approved_at IS NOT NULL)", name="chapter_release_approved"
        ),
    )
    op.create_index(
        "chapter_release_one_draft",
        "chapter_releases",
        ["chapter_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )
    op.create_index("chapter_releases_book", "chapter_releases", ["book_id"])

    op.create_table(
        "book_releases",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("book_id", UUID, _deferred("book_editions.id"), nullable=False),
        sa.Column("version_major", sa.Integer(), nullable=False),
        sa.Column("version_minor", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("status", sa.Enum("BUILT", "PASSED", name="book_release_status"), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("created_by_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_times(),
        sa.UniqueConstraint(
            "book_id", "version_major", "version_minor", name="book_release_version"
        ),
        sa.UniqueConstraint("book_id", "manifest_hash", name="book_release_manifest"),
    )

    op.create_table(
        "book_release_chapters",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "release_id",
            UUID,
            sa.ForeignKey("book_releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chapter_release_id",
            UUID,
            _deferred("chapter_releases.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        *_times(),
        sa.UniqueConstraint("release_id", "position", name="book_release_chapter_position"),
        sa.UniqueConstraint("release_id", "chapter_release_id", name="book_release_chapter_once"),
    )

    op.execute(
        """
        CREATE FUNCTION chapter_release_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'APPROVED' AND pg_trigger_depth() < 2 THEN
                    RAISE EXCEPTION 'Утверждённая версия главы % не удаляется', OLD.code
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.status = 'APPROVED' THEN
                RAISE EXCEPTION 'Утверждённая версия главы % неизменяема', OLD.code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF (NEW.manifest, NEW.manifest_hash, NEW.revision_set_hash, NEW.version_major,
                NEW.version_minor, NEW.code, NEW.chapter_id, NEW.book_id, NEW.master_id)
               IS DISTINCT FROM
               (OLD.manifest, OLD.manifest_hash, OLD.revision_set_hash, OLD.version_major,
                OLD.version_minor, OLD.code, OLD.chapter_id, OLD.book_id, OLD.master_id) THEN
                RAISE EXCEPTION 'Состав версии главы % не меняется', OLD.code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER chapter_releases_guard
        BEFORE UPDATE OR DELETE ON chapter_releases
        FOR EACH ROW EXECUTE FUNCTION chapter_release_guard()
        """
    )
    op.execute(
        """
        CREATE FUNCTION book_release_guard() RETURNS trigger AS $$
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

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER book_releases_guard
        BEFORE UPDATE OR DELETE ON book_releases
        FOR EACH ROW EXECUTE FUNCTION book_release_guard()
        """
    )
    op.execute(
        """
        CREATE FUNCTION book_release_chapter_guard() RETURNS trigger AS $$
        BEGIN
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'Состав выпуска не меняется'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER book_release_chapters_guard
        BEFORE UPDATE OR DELETE ON book_release_chapters
        FOR EACH ROW EXECUTE FUNCTION book_release_chapter_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER book_release_chapters_guard ON book_release_chapters")
    op.execute("DROP FUNCTION book_release_chapter_guard()")
    op.execute("DROP TRIGGER book_releases_guard ON book_releases")
    op.execute("DROP FUNCTION book_release_guard()")
    op.execute("DROP TRIGGER chapter_releases_guard ON chapter_releases")
    op.execute("DROP FUNCTION chapter_release_guard()")
    op.drop_table("book_release_chapters")
    op.drop_table("book_releases")
    op.drop_index("chapter_releases_book", table_name="chapter_releases")
    op.drop_index("chapter_release_one_draft", table_name="chapter_releases")
    op.drop_table("chapter_releases")
    op.execute("DROP TYPE book_release_status")
    op.execute("DROP TYPE release_status")
