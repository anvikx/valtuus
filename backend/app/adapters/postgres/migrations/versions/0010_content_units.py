"""Retain content units for search; older images can omit the nullable columns."""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # The early local catalog build used revision 0009 for content columns. Main now
    # uses 0009 for audit links, so reconcile either schema without losing local data.
    inspector = sa.inspect(op.get_bind())
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    for name in ("content_unit", "content_source"):
        if name not in product_columns:
            op.add_column("products", sa.Column(name, sa.Text(), nullable=True))
    audit_columns = {column["name"] for column in inspector.get_columns("audit_records")}
    for name in ("request_id", "buyer_id"):
        if name not in audit_columns:
            op.add_column("audit_records", sa.Column(name, sa.Text(), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("audit_records")}
    if "ix_audit_records_request_id" not in indexes:
        op.create_index("ix_audit_records_request_id", "audit_records", ["request_id"])


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward only")
