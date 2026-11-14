"""Map declarations conservatively for allergen decisions."""

from typing import Any

from app.domain.catalog import Allergens
from app.domain.enums import AllergenStatus


def map_allergens(classifications: list[dict[str, Any]]) -> Allergens:
    contains: set[str] = set()
    free: set[str] = set()
    unknown = False
    declared = False
    for group in classifications:
        if group.get("name") not in ("allergen", "nonAllergen"):
            continue
        for item in group.get("values") or []:
            code = item.get("id")
            status = item.get("unit")
            if not code:
                unknown = True
                continue
            if status in ("CONTAINS", "MAY_CONTAIN"):
                contains.add(code)
                declared = True
            elif status == "FREE_FROM":
                free.add(code)
                declared = True
            else:
                unknown = True
    return Allergens(
        status=AllergenStatus.KNOWN if declared and not unknown else AllergenStatus.UNKNOWN,
        contains=tuple(sorted(contains)),
        free_from=tuple(sorted(free - contains)),
    )
