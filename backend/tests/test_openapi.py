from app.main import create_app

_CHECKOUT = "/api/v1/carts/{cart_id}/checkout"
_OFFERS = "/api/v1/offers"
_AUDIT = "/api/v1/audit/{cart_id}"
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


def test_route_page_lists_the_response_fields() -> None:
    """The field table is built from the schema, so the page and the schema cannot differ."""
    operation = create_app().openapi()["paths"][_CHECKOUT]["post"]

    assert "**Response fields**" in operation["description"]
    assert (
        "| `lines[].unit_price` | Price per sales unit, EUR ex VAT. |" in operation["description"]
    )


def test_field_table_reaches_nested_fields() -> None:
    """A nested field with no row is a field the agent cannot look up."""
    paths = create_app().openapi()["paths"]
    offers = paths[_OFFERS]["post"]["description"]
    audit = paths[_AUDIT]["get"]["description"]

    # Optional model in a list, a list in an optional model, and a field read by its wire name.
    assert "| `lines[].substitute_for.basis` |" in offers
    assert "| `proposed_split.lines[].qty` |" in offers
    assert "| `records[].input` |" in audit
