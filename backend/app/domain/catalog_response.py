"""Category summaries and fixed advice over the complete filtered search result."""

from collections import defaultdict
from collections.abc import Sequence

from app.domain.catalog import CategorySummary, Product, SearchHint
from app.domain.catalog_search import category_key
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
    SearchHintCode.GUARD_CUT: "The list is not complete. Add an attribute, a unit or more words.",
    SearchHintCode.READY: (
        "The list has every product of this type. Call get_offers with all candidates."
    ),
}


def search_hint(
    candidate_count: int,
    category_hits: int,
    eligible_excluded_count: int,
    missing_fields: tuple[str, ...],
) -> SearchHint:
    if candidate_count == 0:
        code = SearchHintCode.EXCLUDED_ONLY if eligible_excluded_count else SearchHintCode.NO_MATCH
    elif missing_fields:
        code = SearchHintCode.MISSING_FIELDS
    elif category_hits > candidate_count:
        code = SearchHintCode.GUARD_CUT
    else:
        code = SearchHintCode.READY
    return SearchHint(code, _HINT_SENTENCES[code])


def _examples(products: Sequence[Product]) -> tuple[str, ...]:
    names = dict.fromkeys(product.name for product in sorted(products, key=lambda p: p.product_id))
    return tuple(names)[:SEARCH_CATEGORY_EXAMPLES]


def summarize_categories(products: Sequence[Product]) -> tuple[CategorySummary, ...]:
    grouped: dict[str, list[Product]] = defaultdict(list)
    for product in products:
        grouped[product.category].append(product)
    ordered = sorted(grouped, key=lambda code: (-len(grouped[code]), category_key(code)))
    return tuple(
        CategorySummary(code, len(grouped[code]), _examples(grouped[code]))
        for code in ordered[:SEARCH_CATEGORY_COUNT]
    )
