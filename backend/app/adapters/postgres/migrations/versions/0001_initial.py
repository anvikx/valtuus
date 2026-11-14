"""Initial tables, and the trigger that keeps the audit log append only.

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The repository has no update or delete, but a bug or a manual query must not be able to
# change the log either. TRUNCATE fires no row trigger, so tests can still clean up.
_CREATE_AUDIT_GUARD = """
CREATE FUNCTION audit_records_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_records is append only';
END;
$$;

CREATE TRIGGER audit_records_append_only
BEFORE UPDATE OR DELETE ON audit_records
FOR EACH ROW EXECUTE FUNCTION audit_records_append_only();
"""

_DROP_AUDIT_GUARD = """
DROP TRIGGER audit_records_append_only ON audit_records;
DROP FUNCTION audit_records_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "mandates",
        sa.Column("buyer_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("buyer_id", "version"),
    )
    op.create_table(
        "agent_keys",
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("buyer_id", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "offers",
        sa.Column("offer_id", sa.Text(), nullable=False),
        sa.Column("buyer_id", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("offer_id"),
    )
    op.create_table(
        "carts",
        sa.Column("cart_id", sa.Text(), nullable=False),
        sa.Column("buyer_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("approve_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("cart_id"),
    )
    op.create_index("ix_carts_buyer_id_state", "carts", ["buyer_id", "state"])
    op.create_table(
        "orders",
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("cart_id", sa.Text(), nullable=False),
        sa.Column("buyer_id", sa.Text(), nullable=False),
        sa.Column("delivery_dates", postgresql.ARRAY(sa.Date()), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("order_id"),
        sa.UniqueConstraint("cart_id"),
    )
    op.create_index("ix_orders_buyer_id", "orders", ["buyer_id"])
    op.create_table(
        "audit_records",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("record_id", sa.Text(), nullable=False),
        sa.Column("cart_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("record_id"),
    )
    op.create_index("ix_audit_records_cart_id", "audit_records", ["cart_id"])
    op.execute(_CREATE_AUDIT_GUARD)
    op.create_table(
        "idempotency_keys",
        sa.Column("buyer_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("result_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("buyer_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.execute(_DROP_AUDIT_GUARD)
    op.drop_table("audit_records")
    op.drop_table("orders")
    op.drop_table("carts")
    op.drop_table("offers")
    op.drop_table("users")
    op.drop_table("agent_keys")
    op.drop_table("mandates")
