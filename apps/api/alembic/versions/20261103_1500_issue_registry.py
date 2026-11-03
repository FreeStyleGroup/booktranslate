"""Реестр ошибок: замечания, лента событий, вложения.

Что найдено, охраняет триггер: снимки, код и ссылки не меняются ни из кода, ни прямым
запросом. Лента не меняется вовсе. Прямое удаление замечания и события отвергается, а каскад
от организации проходит: внутри него триггер срабатывает на глубине больше единицы.

Revision ID: 0019_issue_registry
Revises: 0018_drop_segments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_issue_registry"
down_revision: str | None = "0018_drop_segments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")

STATUSES = (
    "NEW",
    "NEEDS_CLARIFICATION",
    "CONFIRMED",
    "FIXED",
    "VERIFIED",
    "CLOSED",
    "REJECTED",
    "REOPENED",
)


def _deferred(target: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, deferrable=True, initially="DEFERRED")


def _user() -> sa.ForeignKey:
    return sa.ForeignKey("users.id", ondelete="SET NULL")


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
        "issues",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("book_id", UUID, _deferred("book_editions.id"), nullable=False),
        sa.Column("chapter_id", UUID, _deferred("chapters.id"), nullable=False),
        sa.Column("block_id", UUID, _deferred("blocks.id")),
        sa.Column("object_id", UUID, _deferred("book_objects.id")),
        sa.Column("parent_issue_id", UUID, _deferred("issues.id")),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
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
                name="issue_category",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("CRITICAL", "MAJOR", "MINOR", name="issue_severity"),
            nullable=False,
        ),
        sa.Column("status", sa.Enum(*STATUSES, name="issue_status"), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("impact_count", sa.Integer(), nullable=False),
        sa.Column("automatic", sa.Boolean(), nullable=False),
        sa.Column("detected_by_id", UUID, _user()),
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column("target_snapshot", sa.Text()),
        sa.Column("discovered_revision_id", UUID, _deferred("translation_revisions.id")),
        sa.Column("discovered_revisions", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("proposed_fix", sa.Text()),
        sa.Column("dedupe_key", sa.String(length=64)),
        sa.Column("reviewed_by_id", UUID, _user()),
        sa.Column("fix_revision_id", UUID, _deferred("translation_revisions.id")),
        sa.Column("fixed_by_id", UUID, _user()),
        sa.Column("fix_checked_by_id", UUID, _user()),
        sa.Column("assignee_id", UUID, _user()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("chapter_id", "number", name="issue_number"),
        sa.UniqueConstraint("organization_id", "code", name="issue_code"),
        sa.CheckConstraint(
            "block_id IS NOT NULL OR object_id IS NOT NULL", name="issue_has_subject"
        ),
        sa.CheckConstraint(
            "status NOT IN ('FIXED', 'VERIFIED', 'CLOSED') OR fix_revision_id IS NOT NULL",
            name="issue_fix_has_revision",
        ),
        sa.CheckConstraint(
            "archived_at IS NULL OR status IN ('CLOSED', 'REJECTED')",
            name="issue_archive_only_decided",
        ),
    )
    op.create_index("issues_book_status", "issues", ["book_id", "status"])
    op.create_index("issues_chapter_status", "issues", ["chapter_id", "status"])
    op.create_index("issues_priority", "issues", ["organization_id", "priority_score"])
    op.create_index("issues_block", "issues", ["block_id"])
    op.create_index("issues_object", "issues", ["object_id"])
    op.create_index("issues_parent", "issues", ["parent_issue_id"])
    op.create_index(
        "issues_dedupe",
        "issues",
        ["organization_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )

    op.create_table(
        "issue_events",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("issue_id", UUID, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "CREATED",
                "STATUS_CHANGED",
                "RECLASSIFIED",
                "ASSIGNED",
                "COMMENTED",
                "ATTACHED",
                "ARCHIVED",
                "RESTORED",
                name="issue_event_kind",
            ),
            nullable=False,
        ),
        sa.Column(
            "from_status", postgresql.ENUM(*STATUSES, name="issue_status", create_type=False)
        ),
        sa.Column("to_status", postgresql.ENUM(*STATUSES, name="issue_status", create_type=False)),
        sa.Column("actor_id", UUID, _user()),
        sa.Column("note", sa.Text()),
        sa.Column("related_revision_id", UUID, _deferred("translation_revisions.id")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        *_timestamps(),
    )
    op.create_index("issue_events_issue", "issue_events", ["issue_id", "created_at"])

    op.create_table(
        "issue_attachments",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("issue_id", UUID, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=60), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_id", UUID, _user()),
        *_timestamps(),
    )
    op.create_index("issue_attachments_issue", "issue_attachments", ["issue_id"])

    op.add_column(
        "workspace_settings",
        sa.Column("two_person_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("workspace_settings", "two_person_review", server_default=None)

    # Что найдено — не меняется. Автор сюда не входит намеренно: при удалении учётной записи
    # база сама очищает ссылку, и это не правка показаний.
    op.execute(
        """
        CREATE FUNCTION issue_findings_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Замечание % не меняет то, что было найдено', OLD.code
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER issues_findings_immutable
        BEFORE UPDATE OF number, code, book_id, chapter_id, block_id, object_id, parent_issue_id,
            automatic, source_snapshot, target_snapshot, discovered_revision_id,
            discovered_revisions, description, proposed_fix, dedupe_key
        ON issues
        FOR EACH ROW EXECUTE FUNCTION issue_findings_immutable()
        """
    )

    # Событие не меняется и не исправляется задним числом: автор снова вне списка по той же
    # причине.
    op.execute(
        """
        CREATE FUNCTION issue_event_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Событие замечания % неизменяемо', OLD.id
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER issue_events_immutable
        BEFORE UPDATE OF issue_id, kind, from_status, to_status, note, related_revision_id, payload
        ON issue_events
        FOR EACH ROW EXECUTE FUNCTION issue_event_immutable()
        """
    )

    # Глубина 1 — это сам запрос `DELETE`, больше — каскад внешнего ключа. Удаление организации
    # должно дойти до конца, а прямое удаление записи реестра не должно пройти никогда.
    op.execute(
        """
        CREATE FUNCTION issue_record_undeletable() RETURNS trigger AS $$
        BEGIN
            IF pg_trigger_depth() < 2 THEN
                RAISE EXCEPTION 'Записи реестра ошибок не удаляются (%)', OLD.id
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("issues", "issue_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_undeletable
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION issue_record_undeletable()
            """
        )


def downgrade() -> None:
    for table in ("issues", "issue_events"):
        op.execute(f"DROP TRIGGER {table}_undeletable ON {table}")
    op.execute("DROP FUNCTION issue_record_undeletable()")
    op.execute("DROP TRIGGER issue_events_immutable ON issue_events")
    op.execute("DROP FUNCTION issue_event_immutable()")
    op.execute("DROP TRIGGER issues_findings_immutable ON issues")
    op.execute("DROP FUNCTION issue_findings_immutable()")

    op.drop_column("workspace_settings", "two_person_review")
    op.drop_table("issue_attachments")
    op.drop_table("issue_events")
    op.drop_table("issues")

    for name in ("issue_event_kind", "issue_status", "issue_severity", "issue_category"):
        sa.Enum(name=name).drop(op.get_bind())
