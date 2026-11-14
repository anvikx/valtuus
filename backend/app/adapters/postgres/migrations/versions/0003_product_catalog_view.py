"""Expose parsed product fields as readable SQL columns."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW product_catalog AS
        SELECT product_id,
            body->>'name' AS name,
            body->>'gtin' AS gtin,
            body->>'brand' AS brand,
            body->>'category' AS category,
            body->>'sales_unit' AS sales_unit,
            (body->'content_per_sales_unit'->>'value')::numeric AS content_amount,
            body->'content_per_sales_unit'->>'unit' AS content_unit,
            body->'content_per_sales_unit'->>'source' AS content_source,
            body->'names' AS names,
            body->'attributes' AS attributes,
            body->'allergens'->>'status' AS allergen_status,
            body->'allergens'->'contains' AS contains_allergens,
            body->'allergens'->'free_from' AS free_from_allergens,
            body->>'country_of_origin' AS country_of_origin,
            body->'labels' AS labels,
            body->'substitute_ids' AS substitute_ids,
            (body->>'delivery_reliability')::numeric AS delivery_reliability,
            (body->>'co2_kg_per_kg')::numeric AS co2_kg_per_kg,
            (body->>'lot_size')::numeric AS lot_size,
            (body->>'is_variable_weight')::boolean AS is_variable_weight,
            body->'deposits' AS deposits,
            body->>'key_ingredients' AS key_ingredients,
            (body->>'fat')::numeric AS fat_per_100,
            (body->>'sugar')::numeric AS sugar_per_100,
            (body->>'protein')::numeric AS protein_per_100
        FROM products
    """)


def downgrade() -> None:
    op.execute("DROP VIEW product_catalog")
