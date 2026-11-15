"""Category summaries and fixed advice over the complete filtered search result."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.catalog import CategorySummary, Product, SearchChoice, SearchHint, SearchQuery
from app.domain.catalog_search import (
    CHOICE_ATTRIBUTES,
    NameMatch,
    category_key,
    is_fixed_phrase,
)
from app.domain.constants import (
    CATEGORY_TIE_SHARE,
    SEARCH_CATEGORY_COUNT,
    SEARCH_CATEGORY_EXAMPLES,
)
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
    SearchHintCode.ASK_CATEGORY: (
        "The words fit more than one product type. Show the buyer the categories with their "
        "example names and ask which one they mean. Search again with that category."
    ),
    SearchHintCode.GUARD_CUT: "The search is not complete. Add an attribute, a unit or more words.",
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
    total_hits: int,
) -> SearchHint:
    # Hits but no candidates: the top categories are too close, so the search listed none.
    if candidate_count == 0 and total_hits:
        code = SearchHintCode.ASK_CATEGORY
    elif candidate_count == 0:
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


@dataclass(frozen=True)
class _CategoryRank:
    code: str
    is_fixed_phrase: bool
    whole_word_hits: int
    hits: int

    def key(self) -> tuple[bool, int, int, tuple[int, int | str]]:
        # "milkshake" hits for "milk" and "ice cream" hits for "cream" are many but weak.
        return (self.is_fixed_phrase, -self.whole_word_hits, -self.hits, category_key(self.code))


def _rank(code: str, hits: Sequence[tuple[Product, NameMatch]], query: str) -> _CategoryRank:
    return _CategoryRank(
        code,
        is_fixed_phrase([product for product, _ in hits], query),
        sum(not match.inside_word for _, match in hits),
        len(hits),
    )


def _share(part: int, whole: int) -> float:
    # Two categories with no whole word hits are equal on that count.
    return part / whole if whole else 1.0


def _clear_leader(ranks: Sequence[_CategoryRank]) -> str | None:
    if len(ranks) < 2:
        return ranks[0].code if ranks else None
    leader, runner = ranks[0], ranks[1]
    if leader.is_fixed_phrase != runner.is_fixed_phrase:
        return leader.code

    # Both counts must be close. "kerma" is one whole word hit in each category, 44 hits to 3.
    share = min(
        _share(runner.whole_word_hits, leader.whole_word_hits),
        _share(runner.hits, leader.hits),
    )
    return None if share >= CATEGORY_TIE_SHARE else leader.code


def summarize_categories(
    hits: Sequence[tuple[Product, NameMatch]],
    requested: str | None,
    query: str,
) -> tuple[CategorySummary, ...]:
    grouped: dict[str, list[tuple[Product, NameMatch]]] = defaultdict(list)
    for hit in hits:
        grouped[hit[0].category].append(hit)
    ranks = sorted((_rank(code, grouped[code], query) for code in grouped), key=_CategoryRank.key)

    # With no requested category, the search lists the best ranked category, or none if unclear.
    listed = requested if requested is not None else _clear_leader(ranks)
    return tuple(
        CategorySummary(
            rank.code,
            rank.hits,
            _examples([product for product, _ in grouped[rank.code]]),
            rank.code == listed,
        )
        for rank in ranks[:SEARCH_CATEGORY_COUNT]
    )
