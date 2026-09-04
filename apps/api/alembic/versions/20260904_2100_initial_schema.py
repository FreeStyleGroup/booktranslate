"""Начальная схема: организации, пользователи, проекты, документы, сегменты

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "OWNER", "ADMIN", "MANAGER", "TRANSLATOR", "REVIEWER", "VIEWER",
                name="membership_role",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_memberships_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("organization_id", "user_id", name=op.f("uq_memberships_organization_user")),
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_language", sa.String(length=20), nullable=False),
        sa.Column("target_language", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_projects_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("organization_id", "slug", name=op.f("uq_projects_organization_slug")),
    )
    op.create_index(op.f("ix_projects_organization_id"), "projects", ["organization_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "source_format",
            sa.Enum("PDF", "DOCX", "HTML", "MARKDOWN", "XLIFF", "EPUB", "TXT", name="document_source_format"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED", "PARSING", "PARSED", "TRANSLATING", "REVIEW", "DONE", "FAILED",
                name="document_status",
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_documents_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_documents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_organization_id"), "documents", ["organization_id"])
    op.create_index(op.f("ix_documents_project_id"), "documents", ["project_id"])
    op.create_index(op.f("ix_documents_status"), "documents", ["status"])
    op.create_index(op.f("ix_documents_content_hash"), "documents", ["content_hash"])

    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "PARAGRAPH", "HEADING", "LIST_ITEM", "TABLE_CELL", "CAPTION", "WARNING", "CODE",
                name="segment_kind",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("NEW", "MACHINE", "MEMORY", "EDITED", "APPROVED", "FLAGGED", name="segment_status"),
            nullable=False,
        ),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("target_text", sa.Text(), nullable=True),
        sa.Column("source_location", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("translation_source", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_segments_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_segments_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_segments")),
        sa.UniqueConstraint("document_id", "position", name=op.f("uq_segments_document_position")),
    )
    op.create_index(op.f("ix_segments_organization_id"), "segments", ["organization_id"])
    op.create_index(op.f("ix_segments_document_id"), "segments", ["document_id"])
    op.create_index(op.f("ix_segments_status"), "segments", ["status"])
    op.create_index(op.f("ix_segments_quality_score"), "segments", ["quality_score"])


def downgrade() -> None:
    op.drop_table("segments")
    op.drop_table("documents")
    op.drop_table("projects")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")

    # Перечисления Postgres живут отдельно от таблиц и после drop_table
    # остаются в базе: повторный upgrade упал бы на «type already exists».
    for enum_name in (
        "segment_status",
        "segment_kind",
        "document_status",
        "document_source_format",
        "membership_role",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
