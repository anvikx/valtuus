"""PostgreSQL storage for a complete, atomically replaced flat catalog."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Select, delete, insert, select

from app.adapters.postgres.database import Database
from app.adapters.postgres.tables import product_deposits, products
from app.domain.catalog import Allergens, ContentPerSalesUnit, Product
from app.domain.catalog_search import normalize_name
from app.domain.enums import AllergenStatus, AllergenType, Unit

_BATCH_SIZE = 500


def _rows(product: Product) -> tuple[dict[str, object], list[dict[str, object]]]:
    declarations = {
        kind.value: list(product.allergens.declarations.get(kind, ())) for kind in AllergenType
    }
    row = {
        "product_id": product.product_id,
        "gtin": product.gtin,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "sales_unit": product.sales_unit,
        "content_per_sales_unit": product.content_per_sales_unit.value
        if product.content_per_sales_unit
        else None,
        "content_unit": product.content_per_sales_unit.unit
        if product.content_per_sales_unit
        else None,
        "content_source": product.content_per_sales_unit.source
        if product.content_per_sales_unit
        else None,
        "attributes": list(product.attributes),
        "allergen": list(product.allergens.contains),
        "allergen_declarations": declarations,
        "names": product.names,
        "non_allergen": list(product.allergens.free_from),
        "allergen_status": product.allergens.status.value,
        "country_of_origin": product.country_of_origin,
        "labels": list(product.labels),
        "substitute_ids": list(product.substitute_ids),
        "delivery_reliability": product.delivery_reliability,
        "co2_kg_per_kg": product.co2_kg_per_kg,
        "lot_size": product.lot_size,
        "is_variable_weight": product.is_variable_weight,
        "key_ingredients": product.key_ingredients,
        "fat": product.fat,
        "sugar": product.sugar,
        "protein": product.protein,
        "search_names": " ".join(normalize_name(name) for name in product.names.values()),
    }
    deposits = [
        {
            "product_id": product.product_id,
            "position": position,
            "material": str(item.get("material", "")),
            "quantity": Decimal(str(item.get("quantity", 0))),
            "unit": str(item.get("unit", "")),
        }
        for position, item in enumerate(product.deposits)
    ]
    return row, deposits


def _product(row: dict[str, object], deposits: list[dict[str, object]]) -> Product:
    name = str(row["name"])
    amount = row["content_per_sales_unit"]
    stored = row["allergen_declarations"]
    # An old image writes only the merged array; preserve those codes and its status.
    declarations = (
        {kind: tuple(stored.get(kind.value, ())) for kind in AllergenType}
        if stored is not None
        else {AllergenType.CONTAINS: tuple(row["allergen"] or ())}
    )
    return Product(
        product_id=str(row["product_id"]),
        gtin=row["gtin"],
        name=name,
        names=dict(row["names"] or {}),
        brand=row["brand"],
        category=str(row["category"]),
        sales_unit=str(row["sales_unit"]),
        content_per_sales_unit=(
            ContentPerSalesUnit(
                Decimal(amount),
                Unit(row["content_unit"]) if row["content_unit"] else None,
                row["content_source"],
            )
            if amount is not None
            else None
        ),
        attributes=tuple(row["attributes"] or ()),
        allergens=Allergens(
            AllergenStatus(row["allergen_status"]),
            tuple(row["non_allergen"] or ()),
            declarations,
        ),
        country_of_origin=row["country_of_origin"],
        labels=tuple(row["labels"] or ()),
        substitute_ids=tuple(row["substitute_ids"] or ()),
        delivery_reliability=row["delivery_reliability"],
        co2_kg_per_kg=row["co2_kg_per_kg"],
        lot_size=row["lot_size"],
        is_variable_weight=row["is_variable_weight"],
        deposits=tuple(deposits),
        key_ingredients=row["key_ingredients"],
        fat=row["fat"],
        sugar=row["sugar"],
        protein=row["protein"],
    )


class PostgresCatalog:
    def __init__(self, database: Database) -> None:
        self._database = database

    def replace(self, catalog: Sequence[Product]) -> None:
        with self._database.transaction():
            connection = self._database.writer()
            connection.execute(delete(product_deposits))
            connection.execute(delete(products))
            for start in range(0, len(catalog), _BATCH_SIZE):
                batch = [_rows(product) for product in catalog[start : start + _BATCH_SIZE]]
                connection.execute(insert(products), [row for row, _ in batch])
                deposits = [item for _, values in batch for item in values]
                if deposits:
                    connection.execute(insert(product_deposits), deposits)

    def _load(self, statement: Select) -> list[Product]:
        with self._database.reader() as connection:
            rows = connection.execute(statement).mappings().all()
            ids = [row["product_id"] for row in rows]
            deposits = (
                connection.execute(
                    select(product_deposits).where(product_deposits.c.product_id.in_(ids))
                )
                .mappings()
                .all()
                if ids
                else []
            )
        grouped: dict[str, list[dict[str, object]]] = {}
        for item in deposits:
            grouped.setdefault(item["product_id"], []).append(
                {"material": item["material"], "quantity": item["quantity"], "unit": item["unit"]}
            )
        return [_product(dict(row), grouped.get(row["product_id"], [])) for row in rows]

    def get(self, product_id: str) -> Product | None:
        found = self._load(select(products).where(products.c.product_id == product_id))
        return found[0] if found else None

    def products(self) -> Sequence[Product]:
        return self._load(select(products))

    def search_names(self, query: str) -> Sequence[Product]:
        words = normalize_name(query).split()
        if not words:
            return []
        statement = select(products)
        for word in words:
            statement = statement.where(products.c.search_names.contains(word, autoescape=True))
        return self._load(statement.order_by(products.c.product_id))
