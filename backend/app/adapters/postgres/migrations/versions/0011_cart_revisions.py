"""Keep every revision of a cart, so a changed cart still shows what came before."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same guard as audit_records: a revision is what someone saw or approved.
_CREATE_GUARD = """
CREATE FUNCTION cart_revisions_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'cart_revisions is append only';
END;
$$;

CREATE TRIGGER cart_revisions_append_only
BEFORE UPDATE OR DELETE ON cart_revisions
FOR EACH ROW EXECUTE FUNCTION cart_revisions_append_only();
"""

# Every cart so far was made by an agent and never changed. Carts store no creation time,
# so the revision gets the migration time.
BACKFILL = """
INSERT INTO cart_revisions (cart_id, revision, author, created_at, body)
SELECT cart_id, 1, 'AGENT', now(), body FROM carts
"""


def upgrade() -> None:
    op.create_table(
        "cart_revisions",
        sa.Column("cart_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("cart_id", "revision"),
    )
    op.execute(_CREATE_GUARD)
    op.execute(BACKFILL)


def downgrade() -> None:
    raise RuntimeError("Migrations are forward only; restore the previous application image")
