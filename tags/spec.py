from dataclasses import dataclass
from typing import Literal

ValueType = Literal["single", "multi", "bool", "text"]


@dataclass(frozen=True)
class TagSpec:
    priority: str
    value_type: ValueType
    values: tuple[str, ...]
    prompt: str
    signals: str | None = None


@dataclass(frozen=True)
class TagDefinition:
    name: str
    priority: str
    value_type: ValueType
    values: tuple[str, ...]
    prompt: str
    signals: str | None = None


def tag(
    *,
    priority: str,
    value_type: ValueType,
    values: tuple[str, ...],
    prompt: str,
    signals: str | None = None,
) -> TagSpec:
    return TagSpec(
        priority=priority,
        value_type=value_type,
        values=values,
        prompt=prompt,
        signals=signals,
    )
