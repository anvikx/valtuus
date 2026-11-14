"""Route descriptions for /api/docs. The field tables come from the schema descriptions, so the
page and the schema cannot tell two stories."""

from types import NoneType, UnionType
from typing import Union, get_args, get_origin

from pydantic import BaseModel

_TABLE_HEAD = "| Field | Meaning |\n|---|---|"


def describe(
    text: str,
    response: type[BaseModel],
    request: type[BaseModel] | None = None,
) -> str:
    """The route text, then one field table for the request (if any) and one for the response."""
    parts = [text.strip()]
    if request is not None:
        parts.append(f"**Request fields**\n\n{_table(request)}")
    parts.append(f"**Response fields**\n\n{_table(response)}")
    return "\n\n".join(parts)


def _table(model: type[BaseModel]) -> str:
    return "\n".join([_TABLE_HEAD, *_rows(model, prefix="")])


def _rows(model: type[BaseModel], prefix: str) -> list[str]:
    # Nested fields get a path, as on the Valio Aimo page: lines[].unit_price.
    rows = []
    for name, field in model.model_fields.items():
        path = f"{prefix}{field.alias or name}"
        meaning = (field.description or "").replace("|", "\\|").replace("\n", " ")
        rows.append(f"| `{path}` | {meaning} |")

        nested, is_list = _nested_model(field.annotation)
        if nested is not None:
            rows.extend(_rows(nested, prefix=f"{path}{'[]' if is_list else ''}."))
    return rows


def _nested_model(annotation: object) -> tuple[type[BaseModel] | None, bool]:
    """The model inside X, X | None or list[X], and whether it was a list."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        inner = [arg for arg in get_args(annotation) if arg is not NoneType]
        return _nested_model(inner[0]) if len(inner) == 1 else (None, False)
    if origin is list:
        model, _ = _nested_model(get_args(annotation)[0])
        return model, model is not None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    return None, False
