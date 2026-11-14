import re

from app.main import create_app

_CHECKOUT = "/api/v1/carts/{cart_id}/checkout"
_OFFERS = "/api/v1/offers"
_SCHEMA_POINTER = re.compile(r"See `(\w+)`\.")
_ERROR_BODY = {"$ref": "#/components/schemas/ErrorBody"}
_ERROR_STATUSES = ("401", "403", "404", "409", "422", "503")


def test_spec_shows_the_real_error_body() -> None:
    """Agents build clients from the spec. A wrong error shape breaks their error handling."""
    spec = create_app().openapi()

    responses = spec["paths"][_CHECKOUT]["post"]["responses"]

    for status in _ERROR_STATUSES:
        assert responses[status]["content"]["application/json"]["schema"] == _ERROR_BODY
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_agent_routes_declare_the_bearer_key() -> None:
    """Without the scheme, a client does not know to send the key, and Swagger cannot try a call."""
    spec = create_app().openapi()

    operation = spec["paths"][_CHECKOUT]["post"]

    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert operation["security"] == [{"HTTPBearer": []}]


def test_every_field_says_what_it_means() -> None:
    """An agent reads the field meaning from the spec. A field with no description is a guess."""
    schemas = create_app().openapi()["components"]["schemas"]

    missing = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        for field, prop in schema.get("properties", {}).items()
        if not prop.get("description")
    ]

    assert missing == []


def test_route_table_lists_top_level_fields_only() -> None:
    """One row per field the route returns. Nested fields live once in the schema, not per route."""
    operation = create_app().openapi()["paths"][_CHECKOUT]["post"]
    description = operation["description"]

    assert "**Response fields**" in description
    assert "| `total_ex_vat` | Order total, EUR ex VAT. |" in description
    assert "lines[]." not in description


def test_nested_field_points_to_its_schema() -> None:
    """The pointer is the only way from a route to the nested fields, so each must resolve."""
    spec = create_app().openapi()
    offers = spec["paths"][_OFFERS]["post"]["description"]

    # A list of models and an optional model.
    assert "| `lines` | Offer lines, best rank first. See `OfferLine`. |" in offers
    assert "See `ProposedSplit`." in offers


def test_every_schema_pointer_resolves() -> None:
    """Pydantic renames a schema when two models share a class name, which breaks the pointer."""
    spec = create_app().openapi()
    schemas = spec["components"]["schemas"]

    dead = [
        f"{path} {name}"
        for path, operations in spec["paths"].items()
        for operation in operations.values()
        for name in _SCHEMA_POINTER.findall(operation.get("description", ""))
        if name not in schemas
    ]

    assert dead == []
