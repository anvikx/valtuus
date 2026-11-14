"""Add the parsed product catalog and its substring index."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "products",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("search_names", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_products_search_names_trgm",
        "products",
        ["search_names"],
        postgresql_using="gin",
        postgresql_ops={"search_names": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_table("products")
