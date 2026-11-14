"""Snapshots cross deploy boundaries, so old and new allergen representations must coexist."""

from dataclasses import replace

from pydantic import TypeAdapter

from app.adapters.postgres.offer_codec import OFFER_CODEC
from app.domain.catalog import Allergens
from app.domain.enums import AllergenStatus, AllergenType
from app.domain.offer import Offer
from tests.adapters import samples


def test_legacy_snapshot_preserves_policy_facts():
    offer = samples.offer()
    body = OFFER_CODEC.dump_python(offer, mode="json")
    del body["lines"][0]["allergens"]["declarations"]

    restored = OFFER_CODEC.validate_python(body)

    assert restored == offer
    assert "declarations" not in body["lines"][0]["allergens"]


def test_new_snapshot_retains_merged_list_for_rollback():
    offer = samples.offer()
    allergens = Allergens(
        AllergenStatus.KNOWN,
        (),
        {
            AllergenType.CONTAINS: ("milk",),
            AllergenType.MAY_CONTAIN: ("nuts", "milk"),
        },
    )
    offer = replace(offer, lines=(replace(offer.lines[0], allergens=allergens),))

    body = OFFER_CODEC.dump_python(offer, mode="json")

    assert body["lines"][0]["allergens"]["contains"] == ["milk", "nuts"]
    assert OFFER_CODEC.validate_python(body) == offer
    # Plain dataclass serialization omits properties; the repository codec supplies this field.
    assert "contains" not in TypeAdapter(Offer).dump_python(offer)["lines"][0]["allergens"]
