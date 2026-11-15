"""Category summaries and fixed advice over the complete filtered search result."""

from collections import defaultdict
from collections.abc import Sequence

from app.domain.catalog import CategorySummary, Product, SearchChoice, SearchHint, SearchQuery
from app.domain.catalog_search import CHOICE_ATTRIBUTES, category_key
from app.domain.constants import SEARCH_CATEGORY_COUNT, SEARCH_CATEGORY_EXAMPLES
from app.domain.enums import SearchHintCode

HINT_CODE_DESCRIPTION = (
    "Follow hint.code: " + ", ".join(code.value for code in SearchHintCode) + "."
)

_HINT_SENTENCES = {
    SearchHintCode.EXCLUDED_ONLY: (
        "Products match, but the buyer's rules remove all of them. Tell the buyer."
    ),
    SearchHintCode.NO_MATCH: "No product matches. Try other words, or fewer words.",
    SearchHintCode.MISSING_FIELDS: "Ask the buyer for the missing values before the offers.",
    SearchHintCode.ASK_CHOICES: (
        "Ask the buyer which choices they need, in one question. Search again with the chosen "
        "codes in required_attributes and the other codes in declined_attributes."
    ),
    SearchHintCode.GUARD_CUT: "The list is not complete. Add an attribute, a unit or more words.",
    SearchHintCode.READY: (
        "The search holds every product of this type. Call get_offers with the request_id "
        "and no product_ids."
    ),
}

_MISSING_FIELDS_AND_CHOICES = (
    "Ask the buyer for the missing values and the choices, in one question, before the offers."
)


def search_hint(
    candidate_count: int,
    category_hits: int,
    eligible_excluded_count: int,
    missing_fields: tuple[str, ...],
    choices: tuple[SearchChoice, ...],
) -> SearchHint:
    if candidate_count == 0:
        code = SearchHintCode.EXCLUDED_ONLY if eligible_excluded_count else SearchHintCode.NO_MATCH
    elif missing_fields:
        code = SearchHintCode.MISSING_FIELDS
    elif choices:
        code = SearchHintCode.ASK_CHOICES
    elif category_hits > candidate_count:
        code = SearchHintCode.GUARD_CUT
    else:
        code = SearchHintCode.READY
    if code is SearchHintCode.MISSING_FIELDS and choices:
        return SearchHint(code, _MISSING_FIELDS_AND_CHOICES)
    return SearchHint(code, _HINT_SENTENCES[code])


def search_choices(products: Sequence[Product], query: SearchQuery) -> tuple[SearchChoice, ...]:
    """Attributes that split the list and that the buyer or the mandate has not settled.

    Example: 'milk' holds plain and lactose free milk, so FREE_FROM_LACTOSE is a choice. An
    attribute on every product, or on none, is not.
    """
    settled = {*query.required_attributes, *query.declined_attributes}
    choices = []
    for attribute in CHOICE_ATTRIBUTES:
        if attribute in settled:
            continue
        hits = sum(attribute in product.attributes for product in products)
        if 0 < hits < len(products):
            choices.append(SearchChoice(attribute, hits))
    return tuple(choices)


def _examples(products: Sequence[Product]) -> tuple[str, ...]:
    names = dict.fromkeys(product.name for product in sorted(products, key=lambda p: p.product_id))
    return tuple(names)[:SEARCH_CATEGORY_EXAMPLES]


def summarize_categories(
    products: Sequence[Product],
    requested: str | None,
) -> tuple[CategorySummary, ...]:
    grouped: dict[str, list[Product]] = defaultdict(list)
    for product in products:
        grouped[product.category].append(product)
    ordered = sorted(grouped, key=lambda code: (-len(grouped[code]), category_key(code)))

    # With no requested category, the search lists the category with the most hits.
    listed = requested if requested is not None else next(iter(ordered), None)
    return tuple(
        CategorySummary(code, len(grouped[code]), _examples(grouped[code]), code == listed)
        for code in ordered[:SEARCH_CATEGORY_COUNT]
    )
