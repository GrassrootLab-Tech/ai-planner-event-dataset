from typing import Annotated, Any

from pydantic import BeforeValidator

from tags.spec import TagDefinition

TagValue = str | list[str] | bool | dict[str, list[str]]


def _as_list(value: Any) -> Any:
    if isinstance(value, str):
        return [value]
    return value


def _as_str(value: Any) -> Any:
    # Models sometimes return [] for "unclassified" single/text tags.
    if isinstance(value, list):
        return value[0] if value else None
    return value


def field_type_for_tag(tag: TagDefinition) -> Any:
    """Simple types for tool input_schema; coerce str↔list mismatches."""
    if tag.name == "licensed_ip_flag":
        return Annotated[list[str], BeforeValidator(_as_list)]

    match tag.value_type:
        case "bool":
            return bool
        case "text" | "single":
            # Optional so empty-list → None from _as_str validates cleanly.
            return Annotated[str | None, BeforeValidator(_as_str)]
        case "multi":
            return Annotated[list[str], BeforeValidator(_as_list)]
