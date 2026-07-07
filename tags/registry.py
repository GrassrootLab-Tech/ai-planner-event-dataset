from tags.definitions import TAGS
from tags.groups import TAG_GROUPS
from tags.spec import TagDefinition, TagSpec


class TagRegistry:
    def __init__(self, tags: dict[str, TagSpec] | None = None) -> None:
        source = tags if tags is not None else TAGS
        self._tags = {
            name: TagDefinition(name=name, **spec.__dict__)
            for name, spec in source.items()
        }
        self._validate_groups()

    def get(self, name: str) -> TagDefinition:
        if name not in self._tags:
            raise KeyError(f"Unknown tag: {name}")
        return self._tags[name]

    def get_many(self, names: list[str]) -> list[TagDefinition]:
        return [self.get(name) for name in names]

    def _validate_groups(self) -> None:
        for group_id, tag_names in TAG_GROUPS.items():
            for tag_name in tag_names:
                if tag_name not in self._tags:
                    raise ValueError(
                        f"Tag '{tag_name}' in group '{group_id}' not found in registry"
                    )
