from typing import Annotated, Any

from pydantic import BeforeValidator

from tags.spec import TagDefinition

TagValue = str | list[str] | bool | dict[str, list[str]]


def _as_list(value: Any) -> Any:
    if isinstance(value, str):
        return [value]
    return value


def _as_str(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def field_type_for_tag(tag: TagDefinition) -> Any:
    """Simple types for tool input_schema; coerce str↔list mismatches."""
    if tag.name == "licensed_ip_flag":
        return Annotated[list[str], BeforeValidator(_as_list)]

    match tag.value_type:
        case "bool":
            return bool
        case "text" | "single":
            return Annotated[str, BeforeValidator(_as_str)]
        case "multi":
            return Annotated[list[str], BeforeValidator(_as_list)]
