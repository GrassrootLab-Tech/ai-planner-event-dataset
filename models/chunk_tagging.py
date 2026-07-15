from typing import Any

from pydantic import BaseModel, create_model

from tags.schema import TagValue, field_type_for_tag
from tags.spec import TagDefinition


def build_result_model(tags: list[TagDefinition]) -> type[BaseModel]:
    tag_fields: dict[str, Any] = {}
    for tag in tags:
        field_type = field_type_for_tag(tag)
        tag_fields[tag.name] = (
            (field_type, ...)
            if tag.value_type == "bool"
            else (field_type | None, None)
        )
    chunk_item_model = create_model(
        "TaggingChunkItem",
        chunk_index=(int, ...),
        **tag_fields,
    )
    return create_model(
        "ArticleTaggingResult",
        chunks=(list[chunk_item_model], ...),  # type: ignore[valid-type]
    )


def chunk_item_to_tag_dict(item: BaseModel) -> dict[str, TagValue]:
    data = item.model_dump(exclude_unset=True, exclude_none=True)
    data.pop("chunk_index", None)
    return data
