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
    return "\n".join([_TABLE_HEAD, *_rows(model)])


def _rows(model: type[BaseModel]) -> list[str]:
    # Top-level fields only. A nested object points to its schema, which Swagger lists once
    # under Schemas, so its fields are not repeated on every route that returns it.
    rows = []
    for name, field in model.model_fields.items():
        meaning = (field.description or "").replace("|", "\\|").replace("\n", " ")
        nested = _nested_model(field.annotation)
        if nested is not None:
            meaning = f"{meaning} See `{nested.__name__}`."
        rows.append(f"| `{field.alias or name}` | {meaning} |")
    return rows


def _nested_model(annotation: object) -> type[BaseModel] | None:
    """The model inside X, X | None or list[X]."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        inner = [arg for arg in get_args(annotation) if arg is not NoneType]
        return _nested_model(inner[0]) if len(inner) == 1 else None
    if origin is list:
        return _nested_model(get_args(annotation)[0])
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None
