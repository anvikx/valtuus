"""Read legacy merged allergen lists and keep snapshots readable by rollback images."""

from typing import Annotated, Any

from pydantic import BeforeValidator, SerializerFunctionWrapHandler, TypeAdapter, WrapSerializer

from app.domain.enums import AllergenType
from app.domain.offer import Offer


def _read_legacy(body: object) -> object:
    if not isinstance(body, dict):
        return body

    body = {**body, "lines": [{**line} for line in body["lines"]]}
    for line in body["lines"]:
        allergens = dict(line["allergens"])
        if "declarations" not in allergens:
            # Historical snapshots merged both positive types; retain their policy meaning.
            allergens["declarations"] = {AllergenType.CONTAINS: allergens.get("contains", [])}
        line["allergens"] = allergens
    return body


def _write_legacy(offer: Offer, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
    body = handler(offer)
    for line, stored in zip(offer.lines, body["lines"], strict=True):
        stored["allergens"]["contains"] = list(line.allergens.contains)
    return body


OFFER_CODEC = TypeAdapter(
    Annotated[Offer, BeforeValidator(_read_legacy), WrapSerializer(_write_legacy)],
)
