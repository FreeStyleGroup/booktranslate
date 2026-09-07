"""Состояние доступа пользователя и администратор площадки

Флаг «включён» заменён состоянием: «ещё не рассмотрели» и «закрыли доступ»
— разные вещи, и по флагу потом невозможно ответить, отклонили заявку или
до неё не дошли руки. Существующие записи переносятся как действующие: они
работали до миграции и обязаны работать после.

Revision ID: 0008_user_access
Revises: 0007_catalog_entries
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_user_access"
down_revision: str | None = "0007_catalog_entries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Тип создаётся отдельной командой: CREATE TYPE выполняется сам только
    # при create_table, а при добавлении колонки его не будет.
    #
    # Значения перечисления — ИМЕНА членов заглавными: SQLAlchemy пишет в
    # базу `.name`, а не `.value`.
    user_status = sa.Enum("PENDING", "ACTIVE", "SUSPENDED", name="user_status")
    user_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING", "ACTIVE", "SUSPENDED", name="user_status", create_type=False
            ),
            nullable=False,
            # Умолчание для новых записей — «ждёт решения»; уже существующие
            # переносятся ниже как действующие.
            server_default="PENDING",
        ),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.add_column(
        "users",
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("status_changed_by_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_users_status_changed_by_id_users",
        "users",
        "users",
        ["status_changed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Кто работал до миграции, продолжает работать; отключённые остаются
    # отключёнными. Молча превратить вторых в ожидающих значило бы выдать
    # закрытый доступ за нерассмотренную заявку.
    op.execute("UPDATE users SET status = 'ACTIVE' WHERE is_active = true")
    op.execute("UPDATE users SET status = 'SUSPENDED' WHERE is_active = false")

    op.drop_column("users", "is_active")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.execute("UPDATE users SET is_active = (status = 'ACTIVE')")

    op.drop_constraint("fk_users_status_changed_by_id_users", "users", type_="foreignkey")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "status_changed_by_id")
    op.drop_column("users", "status_changed_at")
    op.drop_column("users", "is_superuser")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_column("users", "status")

    sa.Enum(name="user_status").drop(op.get_bind(), checkfirst=True)
