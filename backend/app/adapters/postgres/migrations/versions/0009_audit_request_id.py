"""Link search and offer audit records to the cart they led to."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable with no backfill: no record written so far has a request_id, and a rollback
    # image still inserts rows without the column.
    op.add_column("audit_records", sa.Column("request_id", sa.Text(), nullable=True))
    op.add_column("audit_records", sa.Column("buyer_id", sa.Text(), nullable=True))
    op.create_index("ix_audit_records_request_id", "audit_records", ["request_id"])


def downgrade() -> None:
    raise RuntimeError("Migrations are forward only; restore the previous application image")
