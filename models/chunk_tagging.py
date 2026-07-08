from typing import Any

from pydantic import BaseModel, create_model

from tags.schema import TagValue, field_type_for_tag
from tags.spec import TagDefinition


def build_result_model(tags: list[TagDefinition]) -> type[BaseModel]:
    tag_fields: dict[str, Any] = {
        tag.name: (field_type_for_tag(tag), ...)
        for tag in tags
    }
    chunk_item_model = create_model(
        "TaggingChunkItem",
        chunk_index=(int, ...),
        **tag_fields,
    )
    return create_model(
        "ArticleTaggingResult",
        chunks=(list[chunk_item_model], ...),  # type: ignore[valid-type]
    )


def chunk_item_to_tag_dict(item: BaseModel, tag_names: list[str]) -> dict[str, TagValue]:
    data = item.model_dump()
    return {name: data[name] for name in tag_names}
