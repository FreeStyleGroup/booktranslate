"""Загрузки словарей, общий словарь площадки, тематика пространства

Запись о каждой загрузке словаря — кто, что и с каким итогом — и
разрешение пространства отдать её термины площадке. Общий словарь
площадки: термины по тематикам, одобренные администратором из таких
загрузок. У пространства появляется тематика: по ней оно получает
подсказки из общего словаря.

Revision ID: 0011_shared_glossary
Revises: 0010_team_and_models
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_shared_glossary"
down_revision: str | None = "0010_team_and_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace_settings", sa.Column("subject", sa.String(length=60), nullable=True))
    op.add_column(
        "workspace_settings",
        sa.Column("share_glossary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "glossary_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("origin", sa.String(length=100), nullable=False),
        sa.Column("source_language", sa.String(length=10), nullable=False),
        sa.Column("target_language", sa.String(length=10), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("added", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_glossary_uploads_organization_id", "glossary_uploads", ["organization_id"]
    )

    op.add_column(
        "glossary_terms", sa.Column("upload_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "glossary_terms_upload_id_fkey",
        "glossary_terms",
        "glossary_uploads",
        ["upload_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_glossary_terms_upload_id", "glossary_terms", ["upload_id"])

    op.create_table(
        "shared_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(length=60), nullable=False),
        sa.Column("source_language", sa.String(length=10), nullable=False),
        sa.Column("target_language", sa.String(length=10), nullable=False),
        sa.Column("source_term", sa.String(length=300), nullable=False),
        sa.Column("source_term_normalized", sa.String(length=300), nullable=False),
        sa.Column("target_term", sa.String(length=300), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        # Тот же тип, что у разряда в словаре пространства: общий термин и
        # есть копия записи словаря.
        sa.Column(
            "kind",
            postgresql.ENUM(name="glossary_entry_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("origin_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin_term_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["origin_organization_id"], ["organizations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["origin_term_id"], ["glossary_terms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "subject",
            "source_language",
            "target_language",
            "source_term_normalized",
            name="shared_term_in_subject",
        ),
    )
    op.create_index("ix_shared_terms_subject", "shared_terms", ["subject"])
    op.create_index(
        "ix_shared_terms_source_term_normalized", "shared_terms", ["source_term_normalized"]
    )


def downgrade() -> None:
    op.drop_index("ix_shared_terms_source_term_normalized", table_name="shared_terms")
    op.drop_index("ix_shared_terms_subject", table_name="shared_terms")
    op.drop_table("shared_terms")

    op.drop_index("ix_glossary_terms_upload_id", table_name="glossary_terms")
    op.drop_constraint("glossary_terms_upload_id_fkey", "glossary_terms", type_="foreignkey")
    op.drop_column("glossary_terms", "upload_id")

    op.drop_index("ix_glossary_uploads_organization_id", table_name="glossary_uploads")
    op.drop_table("glossary_uploads")

    op.drop_column("workspace_settings", "share_glossary")
    op.drop_column("workspace_settings", "subject")
