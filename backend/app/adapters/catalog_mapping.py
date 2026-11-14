"""Convert individual catalog records into domain products."""

from decimal import Decimal
from typing import Any

from app.adapters.catalog_allergens import map_allergens
from app.adapters.catalog_content import map_content
from app.adapters.catalog_nutrition import map_nutrients
from app.domain.catalog import Product
from app.domain.catalog_search import VALID_ATTRIBUTES
from app.domain.product_attributes import is_uht


def _required(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid {key}")
    return value


def _codes(groups: list[dict[str, Any]], name: str) -> tuple[str, ...]:
    return tuple(
        item["id"]
        for group in groups
        if group.get("name") == name
        for item in group.get("values") or []
        if isinstance(item.get("id"), str)
    )


def map_product(
    record: dict[str, Any], reliability: Decimal | None, carbon: Decimal | None
) -> Product:
    product_id = _required(record, "id")
    category = _required(record, "category")
    sales_unit = _required(record, "salesUnit")
    synkka = record.get("synkkaData") or {}
    if not isinstance(synkka, dict):
        raise ValueError("invalid synkkaData")
    source_names = {
        entry["language"]: entry["value"]
        for entry in synkka.get("names") or []
        if isinstance(entry, dict)
        and isinstance(entry.get("language"), str)
        and isinstance(entry.get("value"), str)
        and entry["value"].strip()
    }
    selected_language = next(
        (language for language in ("en", "fi") if language in source_names),
        next(iter(source_names), None),
    )
    if selected_language is None:
        raise ValueError("missing product names")
    name = source_names[selected_language]
    names = {
        language: source_names[language]
        for language in ("en", "fi", "sv")
        if language in source_names
    }
    if not names:
        names = {selected_language: name}
    groups = synkka.get("classifications") or []
    claims = _codes(groups, "nutritionalClaim")
    attributes = claims + (("UHT",) if is_uht(source_names.values()) else ())
    content = map_content(record, list(source_names.values()))
    lot = record.get("allowedLotSize")
    if isinstance(lot, bool) or not isinstance(lot, (int, Decimal)) or lot <= 0:
        raise ValueError("missing or invalid allowedLotSize")
    nutrition = synkka.get("nutritionalContent") or []
    nutrients = map_nutrients(nutrition)
    ingredient_texts = synkka.get("keyIngredients") or []
    ingredient_map = {item.get("language"): item.get("value") for item in ingredient_texts}
    brand = synkka.get("brand")
    labels = _codes(groups, "packagingMarkedLabel")
    return Product(
        product_id=product_id,
        gtin=record.get("salesUnitGtin"),
        name=name,
        names=names,
        brand=brand.strip() or None if isinstance(brand, str) else None,
        category=category,
        sales_unit=sales_unit,
        content_per_sales_unit=content,
        attributes=tuple(
            dict.fromkeys(
                attributes + tuple(label for label in labels if label in VALID_ATTRIBUTES)
            )
        ),
        allergens=map_allergens(groups),
        country_of_origin=record.get("countryOfOrigin"),
        labels=labels,
        substitute_ids=tuple(
            item["substituteProduct"]
            for item in record.get("substitutions") or []
            if item.get("substituteProduct")
        ),
        delivery_reliability=reliability,
        co2_kg_per_kg=carbon,
        lot_size=Decimal(lot),
        is_variable_weight=synkka.get("variableUnit") is True,
        deposits=tuple(record.get("deposits") or ()),
        ingredients=tuple(synkka.get("ingredients") or ()),
        ingredient_texts=tuple(ingredient_texts),
        nutrition=tuple(nutrition),
        nutritional_claims=claims,
        packaging_labels=labels,
        key_ingredients=ingredient_map.get("en") or ingredient_map.get("fi"),
        fat=nutrients.get("FAT"),
        sugar=nutrients.get("SUGAR-"),
        protein=nutrients.get("PRO-"),
    )
