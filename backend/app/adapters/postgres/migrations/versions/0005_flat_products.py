"""Flatten parsed product fields and normalize deposits."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS product_catalog")
    op.drop_table("products")
    op.create_table(
        "products",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("gtin", sa.Text()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("sales_unit", sa.Text(), nullable=False),
        sa.Column("content_per_sales_unit", sa.Numeric()),
        sa.Column("attributes", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("allergen", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("non_allergen", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("allergen_status", sa.Text(), nullable=False),
        sa.Column("country_of_origin", sa.Text()),
        sa.Column("labels", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("substitute_ids", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("delivery_reliability", sa.Numeric()),
        sa.Column("co2_kg_per_kg", sa.Numeric()),
        sa.Column("lot_size", sa.Numeric(), nullable=False),
        sa.Column("is_variable_weight", sa.Boolean(), nullable=False),
        sa.Column("key_ingredients", sa.Text()),
        sa.Column("fat", sa.Numeric()),
        sa.Column("sugar", sa.Numeric()),
        sa.Column("protein", sa.Numeric()),
        sa.Column("search_names", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_products_search_names_trgm",
        "products",
        ["search_names"],
        postgresql_using="gin",
        postgresql_ops={"search_names": "gin_trgm_ops"},
    )
    op.create_table(
        "product_deposits",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("material", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("product_id", "position"),
    )
    op.create_index("ix_product_deposits_product_id", "product_deposits", ["product_id"])


def downgrade() -> None:
    raise RuntimeError("Restore a database backup to reverse the catalog flattening")
