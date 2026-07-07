from typing import Any, Literal

from tags.spec import TagDefinition

TagValue = str | list[str] | bool | dict[str, list[str]]


def _literal_type(values: tuple[str, ...]) -> Any:
    if not values:
        return str
    return Literal.__getitem__(values)


def field_type_for_tag(tag: TagDefinition) -> Any:
    if tag.name == "licensed_ip_flag":
        return list[str]

    match tag.value_type:
        case "bool":
            return bool
        case "text":
            return str
        case "multi":
            return list[_literal_type(tag.values)]
        case "single":
            return _literal_type(tag.values)
