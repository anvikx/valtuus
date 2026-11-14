"""Build candidate quantities without treating unknown content as a known pack."""

from app.domain.catalog import Product, SearchCandidate, SearchQuery
from app.domain.catalog_search import NameMatch
from app.domain.units import fits_request, quantity_delivered, sales_units_needed


def candidate(product: Product, match: NameMatch, query: SearchQuery) -> SearchCandidate:
    content = product.content_per_sales_unit
    count = delivered = excess = None
    if query.quantity is not None and query.unit is not None and fits_request(content, query.unit):
        count = sales_units_needed(query.quantity, query.unit, content)
        delivered = quantity_delivered(count, query.unit, content)
        excess = delivered - query.quantity
    return SearchCandidate(
        product_id=product.product_id,
        gtin=product.gtin,
        name=product.name,
        brand=product.brand,
        sales_unit=product.sales_unit,
        content_per_sales_unit=content,
        sales_units_needed=count,
        quantity_delivered=delivered,
        quantity_over_request=excess,
        attributes=product.attributes,
        allergens=product.allergens,
        country_of_origin=product.country_of_origin,
        labels=product.labels,
        is_substitute_for=None,
        match=match.kind,
    )
