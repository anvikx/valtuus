"""Pure name matching and search validation, shared by every catalog adapter."""

import re
import unicodedata
from dataclasses import dataclass

from app.domain.catalog import Product, SearchQuery
from app.domain.constants import MAX_QUERY_WORDS, MIN_QUERY_LETTERS
from app.domain.enums import SearchMatch, Unit
from app.domain.errors import InvalidRequestError

VALID_ATTRIBUTES = (
    "FREE_FROM_LACTOSE",
    "FREE_FROM_GLUTEN",
    "VEGAN",
    "VEGETARIAN",
    "FREE_FROM_PRESERVATIVES",
    "FREE_FROM_COLOURING_AGENTS",
    "FREE_FROM_ADDITIVES",
    "NO_ADDED_SUGARS",
    "HIGH_FIBRE",
    "FREE_FROM_EGGS",
    "HIGH_PROTEIN",
    "LOW_SODIUM_SALT",
    "FREE_FROM_SWEETENERS",
    "FREE_FROM_SOY",
    "LOW_LACTOSE",
    "FREE_FROM_FAT",
    "FREE_FROM_WHEAT",
    "LOW_FAT",
    "FREE_FROM_ARTIFICIAL_SWEETENERS",
    "FREE_FROM_GMO",
    "FREE_FROM_SODIUM_SALT",
    "UHT",
    "EU_ORGANIC_FARMING",
    "GOODS_FROM_FINLAND_BLUE_SWAN",
    "MADE_IN_FINLAND_FLAG_WITH_KEY",
    "FINNISH_HEART_SYMBOL",
    "RAINFOREST_ALLIANCE",
    "MARINE_STEWARDSHIP_COUNCIL_LABEL",
    "FAIR_TRADE_MARK",
)
ATTRIBUTE_DESCRIPTION = "Valid attribute codes: " + ", ".join(VALID_ATTRIBUTES) + "."


def normalize_name(name: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", name.casefold())
        if not unicodedata.combining(char)
    )


def validate_query(query: SearchQuery) -> str:
    words = normalize_name(query.query).split()
    if not 1 <= len(words) <= MAX_QUERY_WORDS or any(
        sum(char.isalpha() for char in word) < MIN_QUERY_LETTERS for word in words
    ):
        raise InvalidRequestError(
            "Search needs 1 to 5 words, each with at least 3 letters.",
            "Use fewer words or words with at least 3 letters.",
        )
    if set(query.required_attributes) - set(VALID_ATTRIBUTES):
        raise InvalidRequestError(
            "Unknown attribute code. " + ATTRIBUTE_DESCRIPTION,
            "Use one of the valid attribute codes.",
        )
    return " ".join(words)


@dataclass(frozen=True, order=True)
class NameMatch:
    inside_word: bool
    words: int

    @property
    def kind(self) -> SearchMatch:
        return SearchMatch.INSIDE_WORD if self.inside_word else SearchMatch.WHOLE_WORD


class NameMatcher:
    def __init__(self, query: str) -> None:
        self._words = query.split()
        self._whole = [re.compile(rf"\b{re.escape(word)}\b") for word in self._words]
        self._negated = [
            re.compile(rf"{re.escape(word)}\w*[\s-]*(?:free|fri|ton|vapaa)\b")
            for word in self._words
        ]

    def match(self, product: Product) -> NameMatch | None:
        matches = [
            match
            for language in ("en", "fi", "sv")
            if (name := product.names.get(language))
            and (match := self._name_match(normalize_name(name))) is not None
        ]
        return min(matches) if matches else None

    def _name_match(self, name: str) -> NameMatch | None:
        if not all(word in name for word in self._words):
            return None
        if any(pattern.search(name) for pattern in self._negated):
            return None
        return NameMatch(
            not all(pattern.search(name) for pattern in self._whole), len(name.split())
        )


def fits_search(product: Product, unit: Unit | None) -> bool:
    content = product.content_per_sales_unit
    if unit not in (Unit.L, Unit.KG) or content is None:
        return True
    opposite = Unit.KG if unit == Unit.L else Unit.L
    return content.unit != opposite


def category_key(category: str) -> tuple[int, int | str]:
    return (0, int(category)) if category.isdecimal() else (1, category)
