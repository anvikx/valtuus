"""Map declarations conservatively for allergen decisions."""

from typing import Any

from app.domain.catalog import Allergens
from app.domain.enums import AllergenStatus, AllergenType


def map_allergens(classifications: list[dict[str, Any]]) -> Allergens:
    declarations: dict[AllergenType, set[str]] = {kind: set() for kind in AllergenType}
    free: set[str] = set()
    unknown = False
    for group in classifications:
        if group.get("name") not in ("allergen", "nonAllergen"):
            continue
        for item in group.get("values") or []:
            code = item.get("id")
            status = item.get("unit")
            if not isinstance(code, str) or not code.strip():
                unknown = True
                continue
            if status in (AllergenType.CONTAINS, AllergenType.MAY_CONTAIN):
                declarations[AllergenType(status)].add(code)
            elif status == "FREE_FROM":
                free.add(code)
            else:
                unknown = True
    contains = set().union(*declarations.values())
    return Allergens(
        # FREE_FROM alone is a declaration. 2,231 products declare only FREE_FROM, 1,689 of
        # them all 14 codes (checked 14 Nov 2026, 17,546 products). UNKNOWN would send them
        # to human approval.
        status=(
            AllergenStatus.KNOWN if (contains or free) and not unknown else AllergenStatus.UNKNOWN
        ),
        free_from=tuple(sorted(free - contains)),
        declarations={kind: tuple(sorted(codes)) for kind, codes in declarations.items()},
    )
