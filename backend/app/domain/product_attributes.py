import re
from collections.abc import Iterable

# The product data has no structured UHT field (checked 14 Nov 2026, 17,546 products), so UHT
# comes from the names. The packagingMarkedLabel warmTemperature is no substitute: 7 of the 17
# UHT milk drinks (category 10400) do not have it.
# Whole word only: 576 names contain "uht" inside a word, for example "Huhtamaki".
_UHT_WORD = re.compile(r"\bUHT\b", re.IGNORECASE)


def is_uht(names: Iterable[str]) -> bool:
    """Return True when any of the product's names (en, fi, sv) has the whole word UHT.

    All languages count, because some products have UHT in only some of their names.
    """
    return any(_UHT_WORD.search(name) for name in names)
