"""Приглашения в рабочее пространство и выбор модели перевода

Доступ в пространство открывает его владелец: приглашённый по ссылке
человек получает действующую учётную запись сразу, без второго одобрения
администратором площадки. В базе — хеш ссылки, а не она сама.

Модель перевода выбирается пространством из каталога; пусто — умолчание
площадки.

Revision ID: 0010_team_and_models
Revises: 0009_translation_jobs
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_team_and_models"
down_revision: str | None = "0009_translation_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        # Тот же тип, что у роли участия: приглашение и превращается в
        # участие с этой ролью. Второе перечисление с теми же значениями
        # разошлось бы с первым при первой новой роли.
        sa.Column(
            "role",
            postgresql.ENUM(name="membership_role", create_type=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="invitations_token_hash"),
    )

    op.create_index("ix_invitations_organization_id", "invitations", ["organization_id"])

    # На одну почту — одно открытое приглашение в пространство.
    op.create_index(
        "invitations_open_email",
        "invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )

    op.create_table(
        "workspace_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Именем, а не ссылкой на каталог: каталог живёт в коде, а выбранное
        # должно пережить его смену и читаться из базы как есть.
        sa.Column("translation_model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", name="workspace_settings_organization"),
    )


def downgrade() -> None:
    op.drop_table("workspace_settings")

    op.drop_index("invitations_open_email", table_name="invitations")
    op.drop_index("ix_invitations_organization_id", table_name="invitations")
    op.drop_table("invitations")
